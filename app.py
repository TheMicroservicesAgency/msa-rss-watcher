from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
import hashlib
import json
import redis
import logging
import requests
import time

# create the scheduler
scheduler = BackgroundScheduler()

# connect to redis
rdb = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)
rcache = redis.StrictRedis(host='localhost', port=6379, db=1, decode_responses=True)

# initialize the Flask app
app = Flask(__name__)


@app.after_request
def add_header(response):
    """Adds headers to all responses disabling upstream caching"""

    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


def update_feed(feed_id):
    """Refresh a given feed by fetching the RSS/Atom URL content, looks for new items 
    and sends notifications to the feed webhook"""

    with app.app_context():

        app.logger.info("updating feed %s" % feed_id)

        # get the feed info from redis
        feed = json.loads(rdb.hget("feeds", feed_id))

        # fetch the feed items, this involves an external HTTP request
        update_time = maya.now().iso8601()

        try:

            start = time.time()
            data = feedparser.parse(feed['url'])
            time_elapsed = time.time() - start
            app.logger.info("fetching %s took %s seconds " % (feed['url'], time_elapsed))
            app.logger.info("got %s items " % len(data.entries))

        except Exception as e:
            app.logger.error("Could not fetch remote URL %s" % feed['url'])
            app.logger.error(e)
            return None

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

                # if that is a new item, add it to the redis cache
                # a very long expiration is used since we want redis to evict
                # the oldest entries automatically when it's full
                one_year_secs = 31556926
                rcache.setex(item_key, one_year_secs, 1)

                # send the notification to the designated webhook
                app.logger.info("sending POST request with new item to %s" % feed['webhook'])

                try:
                    start = time.time()

                    headers = {'Content-Type': 'application/json', 'user-agent': 'msa-rss-watcher'}
                    requests.post(feed['webhook'], json.dumps({'data': new_item}), headers=headers)

                    time_elapsed = time.time() - start
                    app.logger.info("sending the notification took %s seconds " % time_elapsed)

                    if 'notifications_sent' not in feed:
                        feed['notifications_sent'] = 1
                    else:
                        feed['notifications_sent'] = feed['notifications_sent'] + 1

                except Exception as e:
                    app.logger.error("Could not send notification to webhook %s" % feed['webhook'])
                    app.logger.error(e)
                    # remove the item from the cache, so that it retries to resend it
                    # at the next update
                    rcache.delete(item_key)


        feed['items_cached'] = len(rcache.keys("%s.*" % feed_id))

        # update the feed timers
        if 'time_first_fetch' not in feed:
            feed['time_first_fetch'] = update_time

        feed['time_last_fetch'] = update_time

        # update the feed items counts
        if 'items_fetched' not in feed:
            feed['items_fetched'] = len(data.entries)
        else:
            feed['items_fetched'] = feed['items_fetched'] + len(data.entries)

        # update the feed info in redis
        rdb.hset('feeds', feed_id, json.dumps(feed))


@app.route('/feeds', methods=['POST'])
def watch_new_feed():
    """Add a new feed and create a job to refresh it at the specified interval"""

    try:
        data = request.json

        if 'feed' in data:

            feed = data['feed']

            if 'url' in feed and 'refresh_secs' in feed and 'webhook' in feed:

                # generate an ID for this new feed
                m = hashlib.sha256()
                m.update(str.encode(feed['url']))
                feed_id = m.hexdigest()[0:6]

                # return an error if the feed already exists
                feed_exists = rdb.hexists('feeds', feed_id)
                if feed_exists:
                    msg = {'errors': [{'title': 'Conflict',
                                       'details': 'A feed for this given URL already exists.'}]}
                    return jsonify(msg), 409

                # create the new feed
                new_feed = {'id': feed_id, 'url': feed['url'],
                            'refresh_secs': feed['refresh_secs'],
                            'webhook': feed['webhook']}

                app.logger.info("creating " + json.dumps(new_feed))
                rdb.hset('feeds', feed_id, json.dumps(new_feed))

                try:
                    # do a quick test of that remote URL
                    requests.get(new_feed['url'])

                    # create a recurring job for this new feed
                    scheduler.add_job(update_feed, 'interval', seconds=int(new_feed['refresh_secs']),
                                      args=[new_feed['id']], id=feed_id)

                    data = {'data': {'feed': new_feed}}
                    response = jsonify(data)
                    return response

                except Exception as e:
                    app.logger.error(e)
                    rdb.hdel('feeds', feed_id)

                    msg = {'errors': [{'title': 'Could not create feed watch', 'details': [str(e)] }] }
                    return jsonify(msg), 400


    except Exception as e:
        app.logger.error(e)
        msg = {'errors': [{'title': 'Could not parse feed', 'details': [str(e)] }] }
        return jsonify(msg), 400

    data = {}
    response = jsonify(data)
    return response


@app.route('/feeds')
def list_all_feeds():
    """Returns the list of feeds currently watched"""

    feeds = []
    for feed_id in rdb.hkeys('feeds'):
        feed = json.loads(rdb.hget('feeds', feed_id))
        feeds.append(feed)

    data = {'data': {'feeds': feeds}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>')
def return_feed_info(feed_id):
    """Returns all info related to a given feed, the feed def. & last items fetched"""

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
    """Stop watching a given feed, and deleted all associated data"""

    feed_exists = rdb.hexists('feeds', feed_id)
    if feed_exists:

        app.logger.info("stopping job for feed %s" % feed_id)

        # unschedule the job related to this feed
        scheduler.remove_job(feed_id)

        feed = json.loads(rdb.hget('feeds', feed_id))

        # delete the feed
        rdb.hdel('feeds', feed_id)

        # remove all additional data related to this feed
        rdb.delete("feed.%s.items" % feed_id)

        cached_items = rcache.keys("%s.*" % feed_id)
        for key in cached_items:
            rcache.delete(key)

        app.logger.info("deleted all data of the feed %s" % feed_id)

        data = {'data': {'feed': feed }}
        response = jsonify(data)
        return response

    else:
        msg = {'errors': [{'title': 'Not found',
                           'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404


@app.route('/redis/info')
def get_redis_info():
    """Return stats about Redis"""

    data = {'data': {'info': rdb.info()}}
    response = jsonify(data)
    return response


def initialize():
    """Initialize the app, starts the scheduler and reloads existing feeds"""

    app.logger.info("starting the scheduler")
    scheduler.start()

    app.logger.info("reloading the list of feeds from redis")

    # reload existing feeds & recreate any jobs if needed
    for feed_id in rdb.hkeys('feeds'):

        feed = json.loads(rdb.hget('feeds', feed_id))

        app.logger.info("reloading the feed %s" % feed_id)
        app.logger.debug("%s" % feed)

        scheduler.add_job(update_feed, 'interval', seconds=int(feed['refresh_secs']),
                          args=[feed['id']], id=feed['id'])


if __name__ == "__main__":

    # setup the logging
    handler = logging.StreamHandler()
    formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)

    initialize()

    app.run(port=8080, threaded=True)
