from flask import Flask, jsonify, redirect, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
from tinydb import TinyDB, Query
from tinydb import where
from tinydb.storages import MemoryStorage
import hashlib
import json
from pybloom import ScalableBloomFilter
import pickle
import codecs


scheduler = BackgroundScheduler() # create the in-memory scheduler

db = TinyDB(storage=MemoryStorage) # initialize the in-memory database

app = Flask(__name__) # initialize the Flask app


@app.before_first_request
def initialize():
    scheduler.start()


def update_feed(feed_id):
    with app.app_context():

        app.logger.debug("updating " + json.dumps(feed_id))

        # get the feed data from the db
        feed_data = db.table('feeds').search(where('id') == feed_id)[0]

        # fetch the feed items, this involves an external HTTP request
        data = feedparser.parse(feed_data['url'])
        feed_update_time = maya.now().iso8601()

        app.logger.debug("got %s items " % len(data.entries))

        # get the bloom filter for this feed, useful to keep track of previously seen items
        results = db.table('feeds_bloom_filters').search(where('id') == feed_id)
        if len(results) == 1:
            print("loading existing sbf")
            pickled_sbf = results[0]['bloom_filter']
            sbf = pickle.loads(codecs.decode(pickled_sbf.encode(), "base64"))
        else:
            print("creating new sbf")
            sbf = ScalableBloomFilter(mode=ScalableBloomFilter.SMALL_SET_GROWTH)

        # clear the feed_x_items table as we only keep the items from the last fetch
        db.purge_table("feed_%s_items" % feed_id)
        feed_items_table = db.table("feed_%s_items" % feed_id)

        for item in data.entries:

            new_item = {
                'title' : item.title,
                'link' : item.link,
                'published' : maya.parse(item.published).iso8601(),
                'summary' : item.summary
            }

            # check if this is the first time we see this item
            if item.link not in sbf:
                print("new item => " + item.link)

                sbf.add(item.link)

                #
                # SEND NOTIFICATION OUT
                #

            feed_items_table.insert(new_item)

        # update the bloom filter in the db
        pickled_sbf = codecs.encode(pickle.dumps(sbf), "base64").decode()
        bloom_filter = {'id': feed_id, 'bloom_filter': pickled_sbf}

        results = db.table('feeds_bloom_filters').search(where('id') == feed_id)
        if len(results) == 1:
            print("updating sbf in db")
            db.table('feeds_bloom_filters').update(bloom_filter, where('id') == feed_id)
        else:
            print("inserting sbf in db")
            db.table('feeds_bloom_filters').insert(bloom_filter)

        # update the feed timers

        if 'time_first_update' not in feed_data:
            feed_data['time_first_update'] = feed_update_time

        feed_data['time_last_update'] = feed_update_time

        # update the feed items counts

        if 'items_fetched_total' not in feed_data:
            feed_data['items_fetched_total'] = len(data.entries)
        else:
            feed_data['items_fetched_total'] = feed_data['items_fetched_total'] + len(data.entries)


        feed_data['items_unique_count'] = len(sbf)

        # update the feed data in the db
        db.table('feeds').update(feed_data, where('id') == feed_id)


@app.route('/feeds', methods=['POST'])
def watch_new_feed():

    try:
        data = request.json

        if 'feed' in data:

            feed = data['feed']

            if 'url' in feed and 'interval' in feed and 'webhook' in feed:

                # generate an ID for this new feed
                m = hashlib.sha256()
                m.update(str.encode(feed['url']))
                id = m.hexdigest()[0:6]

                new_feed = {'id': id, 'url': feed['url'], 'interval': feed['interval'],
                            'webhook': feed['webhook']}

                app.logger.debug("creating " + json.dumps(new_feed))

                feeds = db.table('feeds')
                feeds.insert(new_feed)

                scheduler.add_job(update_feed, 'interval', seconds=int(feed['interval']),
                                  args=[new_feed['id']], id=id)

    except Exception as e:
        print(e)
        msg = {'ERROR': 'Could not parse feed.'}
        return jsonify(msg), 400


    data = {}
    response = jsonify(data)
    return response


@app.route('/feeds')
def list_watched_feeds():
    feeds = db.table('feeds')
    data = {'data': {'feeds': feeds.all()}}
    response = jsonify(data)
    return response


@app.route('/feeds/<id>')
def return_feed_items(id):

    feeds = db.table('feeds')
    feed = feeds.search(where('id') == id)[0]

    feed_items_table = "feed_%s_items" % id
    feed_items = db.table(feed_items_table)

    feed['items'] = feed_items.all()

    data = {'data': {'feed': feed}}
    response = jsonify(data)
    return response


@app.route('/feeds', methods=['DELETE'])
def stop_watching_feed():
    data = {}
    response = jsonify(data)
    return response


if __name__ == "__main__":

    app.run(debug=True, port=8080, threaded=True)
    # app.run(port=8080, threaded=True)
