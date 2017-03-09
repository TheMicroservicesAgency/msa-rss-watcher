from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
from tinydb import TinyDB, where, Query
from tinydb.operations import increment
import hashlib
import json

scheduler = BackgroundScheduler() # create the scheduler

db = TinyDB('/data/db.json') # initialize the database

app = Flask(__name__) # initialize the Flask app


def update_feed(feed_id):
    with app.app_context():

        app.logger.debug("updating " + json.dumps(feed_id))

        # get the feed data from the db
        feed_data = db.table('feeds').search(where('id') == feed_id)[0]

        # fetch the feed items, this involves an external HTTP request
        data = feedparser.parse(feed_data['url'])
        feed_fetch_time = maya.now().iso8601()

        app.logger.debug("got %s items " % len(data.entries))

        # clear the feed_x_items table as we only keep the items from the last fetch
        db.purge_table("feed_%s_last_items" % feed_id)
        feed_items_table = db.table("feed_%s_last_items" % feed_id)
        feed_cache_table = db.table("feed_%s_cache" % feed_id)

        for item in data.entries:

            new_item = {
                'title' : item.title,
                'link' : item.link,
                'published' : maya.parse(item.published).iso8601(),
                'summary' : item.summary
            }

            feed_items_table.insert(new_item) # add it to the last items fetched table

            # check if we have seen this item before
            results = feed_cache_table.search(where('link') == item.link)
            if len(results) == 0:

                app.logger.debug("new item => " + item.link)

                # if that is a new item, add it to the cache
                feed_cache_table.insert({'link': item.link, 'ttl' : 0})

                #
                # SEND NOTIFICATION OUT
                #

                if 'notifications_sent' not in feed_data:
                    feed_data['notifications_sent'] = 1
                else:
                    feed_data['notifications_sent'] = feed_data['notifications_sent'] + 1


        # update the ttl of the items in the cache
        feed_cache_table.update(increment('ttl'), Query().ttl.exists())

        # remove old entries in the cache
        item = Query()
        feed_cache_table.remove(item.ttl > 3)

        feed_data['items_cached'] = len(feed_cache_table)

        # update the feed timers
        if 'time_first_fetch' not in feed_data:
            feed_data['time_first_fetch'] = feed_fetch_time

        feed_data['time_last_fetch'] = feed_fetch_time

        # update the feed items counts
        if 'items_fetched' not in feed_data:
            feed_data['items_fetched'] = len(data.entries)
        else:
            feed_data['items_fetched'] = feed_data['items_fetched'] + len(data.entries)

        # update the feed data in the db
        db.table('feeds').update(feed_data, where('id') == feed_id)


@app.before_first_request
def initialize():
    scheduler.start()

    # recreate any jobs if needed
    feeds = db.table('feeds')
    for feed in feeds.all():
        scheduler.add_job(update_feed, 'interval', seconds=int(feed['fetch_interval_secs']), args=[feed['id']], id=feed['id'])



@app.route('/feeds', methods=['POST'])
def watch_new_feed():

    try:
        data = request.json

        if 'feed' in data:

            feed = data['feed']

            if 'url' in feed and 'fetch_interval_secs' in feed and 'webhook' in feed:

                # generate an ID for this new feed
                m = hashlib.sha256()
                m.update(str.encode(feed['url']))
                id = m.hexdigest()[0:6]

                new_feed = {'id': id, 'url': feed['url'], 'fetch_interval_secs': feed['fetch_interval_secs'],
                            'webhook': feed['webhook']}

                app.logger.debug("creating " + json.dumps(new_feed))

                feeds = db.table('feeds')
                feeds.insert(new_feed)

                scheduler.add_job(update_feed, 'interval', seconds=int(feed['fetch_interval_secs']),
                                  args=[new_feed['id']], id=id)


    except Exception as e:
        app.logger.error(e)
        msg = {'errors': [{'title': 'Could not parse feed', 'details': ''}]}
        return jsonify(msg), 400


    data = {}
    response = jsonify(data)
    return response


@app.route('/feeds')
def list_all_feeds():
    feeds = db.table('feeds')
    data = {'data': {'feeds': feeds.all()}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>')
def return_feed_info(feed_id):

    feeds = db.table('feeds')
    results = feeds.search(where('id') == feed_id)

    if len(results) == 0:
        msg = {'errors': [{'title': 'Not found', 'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    feed = results[0]
    feed_last_items = db.table("feed_%s_last_items" % feed_id)

    data = {'data': {'feed': feed, 'feed_last_items': feed_last_items.all()}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>', methods=['DELETE'])
def stop_watching_feed(feed_id):

    # remove the feed from the db
    feeds = db.table('feeds')
    results = feeds.search(where('id') == feed_id)

    if len(results) == 0:
        msg = {'errors': [{'title': 'Not found', 'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    # unschedule the job related to this feed
    scheduler.remove_job(feed_id)

    if len(results) == 1:
        feed = results[0]
        feeds.remove(eids=[feed.eid])

    # remove all additional data related to this feed from the db
    db.purge_table("feed_%s_last_items" % feed_id)
    db.purge_table("feed_%s_cache" % feed_id)


if __name__ == "__main__":

    app.run(debug=True, port=8080, threaded=True)
    # app.run(port=8080, threaded=True)
