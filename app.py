from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
import hashlib
import json
import redis

# create the scheduler
scheduler = BackgroundScheduler()

# connect to redis
rdb = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)
rcache = redis.StrictRedis(host='localhost', port=6379, db=1, decode_responses=True)

# initialize the Flask app
app = Flask(__name__)


def update_feed(feed_id):
    with app.app_context():

        app.logger.debug("updating " + json.dumps(feed_id))

        # get the feed info from redis
        feed = json.loads(rdb.hget("feeds", feed_id))

        # fetch the feed items, this involves an external HTTP request
        data = feedparser.parse(feed['url'])
        feed_fetch_time = maya.now().iso8601()

        app.logger.debug("got %s items " % len(data.entries))

        feed_items = "feed.%s.items" % feed_id

        # clear the items set as we only keep the items from the last fetch
        rdb.delete(feed_items)

        for item in data.entries:

            new_item = {
                'title': item.title,
                'link': item.link,
                'published': maya.parse(item.published).iso8601(),
                'summary': item.summary
            }

            # add it to the last items set
            rdb.sadd(feed_items, json.dumps(new_item))

            # check if we have seen this item before
            item_key = "%s.%s" % (feed_id, item.link)
            already_seen = rcache.get(item_key) != None

            if not already_seen:

                app.logger.debug("new item => " + item.link)

                # if that is a new item, add it to the cache
                one_year_secs = 31556926
                rcache.setex(item_key, one_year_secs, 1)

                #
                # SEND NOTIFICATION OUT
                #

                if 'notifications_sent' not in feed:
                    feed['notifications_sent'] = 1
                else:
                    feed['notifications_sent'] = feed['notifications_sent'] + 1

        feed['items_cached'] = len(rcache.keys("%s.*" % feed_id))

        # update the feed timers
        if 'time_first_fetch' not in feed:
            feed['time_first_fetch'] = feed_fetch_time

        feed['time_last_fetch'] = feed_fetch_time

        # update the feed items counts
        if 'items_fetched' not in feed:
            feed['items_fetched'] = len(data.entries)
        else:
            feed['items_fetched'] = feed['items_fetched'] + len(data.entries)

        # update the feed info in redis
        rdb.hset('feeds', feed_id, json.dumps(feed))


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
                feed_id = m.hexdigest()[0:6]

                feed_exists = rdb.hexists('feeds', feed_id)
                if feed_exists:
                    msg = {'errors': [{'title': 'Conflict',
                                       'details': 'A feed for this given URL already exists.'}]}
                    return jsonify(msg), 409

                new_feed = {'id': feed_id, 'url': feed['url'],
                            'fetch_interval_secs': feed['fetch_interval_secs'],
                            'webhook': feed['webhook']}

                app.logger.debug("creating " + json.dumps(new_feed))

                rdb.hset('feeds', feed_id, json.dumps(new_feed))

                try:

                    update_feed(feed_id)

                    scheduler.add_job(update_feed, 'interval',
                                      seconds=int(feed['fetch_interval_secs']),
                                      args=[new_feed['id']], id=feed_id)

                except Exception as e:
                    app.logger.error(e)
                    rdb.hdel('feeds', feed_id)


    except Exception as e:
        app.logger.error(e)
        msg = {'errors': [{'title': 'Could not parse feed', 'details': ''}]}
        return jsonify(msg), 400

    data = {}
    response = jsonify(data)
    return response


@app.route('/feeds')
def list_all_feeds():
    feeds = []
    for feed_id in rdb.hkeys('feeds'):
        feed = json.loads(rdb.hget('feeds', feed_id))
        feeds.append(feed)

    data = {'data': {'feeds': feeds}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>')
def return_feed_info(feed_id):
    feed_exists = rdb.hexists('feeds', feed_id)
    if not feed_exists:
        msg = {'errors': [{'title': 'Not found',
                           'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    # get the feed info and all the current items
    feed = json.loads(rdb.hget('feeds', feed_id))

    items = []
    for item in rdb.smembers("feed.%s.items" % feed_id):
        items.append(json.loads(item))

    data = {'data': {'feed': feed, 'feed_last_items': items}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>', methods=['DELETE'])
def stop_watching_feed(feed_id):

    feed_exists = rdb.hexists('feeds', feed_id)
    if feed_exists:

        # unschedule the job related to this feed
        scheduler.remove_job(feed_id)

        feed = rdb.hget('feeds', feed_id)

        # delete the feed
        rdb.hdel('feeds', feed_id)

        # remove all additional data related to this feed
        rdb.delete("feed.%s.items" % feed_id)

        cached_items = rcache.keys("%s.*" % feed_id)
        for key in cached_items:
            rcache.delete(key)

        data = {'data': {'feed': feed }}
        response = jsonify(data)
        return response

    else:
        msg = {'errors': [{'title': 'Not found',
                           'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404


@app.route('/redis/info')
def get_redis_info():
    # return metrics about redis
    data = {'data': {'info': rdb.info()}}
    response = jsonify(data)
    return response


def initialize():
    scheduler.start()

    # recreate any jobs if needed
    for feed_id in rdb.hkeys('feeds'):
        feed = json.loads(rdb.hget('feeds', feed_id))

        scheduler.add_job(update_feed, 'interval', seconds=int(feed['fetch_interval_secs']),
                          args=[feed['id']], id=feed['id'])


if __name__ == "__main__":
    initialize()
    app.run(debug=True, port=8080, threaded=True)
    # app.run(port=8080, threaded=True)
