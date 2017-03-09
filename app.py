from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
import hashlib
import json
import redis

scheduler = BackgroundScheduler()  # create the scheduler

r = redis.StrictRedis(host='localhost', port=6379, decode_responses=True)  # connect to redis

app = Flask(__name__)  # initialize the Flask app


def update_feed(feed_id):
    with app.app_context():

        app.logger.debug("updating " + json.dumps(feed_id))

        # get the feed info from redis
        feed = json.loads(r.hget("feeds", feed_id))

        # fetch the feed items, this involves an external HTTP request
        data = feedparser.parse(feed['url'])
        feed_fetch_time = maya.now().iso8601()

        app.logger.debug("got %s items " % len(data.entries))

        feed_items = "feed_%s_items" % feed_id
        feed_cache = "feed_%s_cache" % feed_id

        # clear the feed_x_items set as we only keep the items from the last fetch
        r.delete(feed_items)

        for item in data.entries:

            new_item = {
                'title': item.title,
                'link': item.link,
                'published': maya.parse(item.published).iso8601(),
                'summary': item.summary
            }

            # add it to the last items set
            r.sadd(feed_items, json.dumps(new_item))

            # check if we have seen this item before
            already_seen = r.sismember(feed_cache, item.link)

            if not already_seen:

                app.logger.debug("new item => " + item.link)

                # if that is a new item, add it to the cache
                r.sadd(feed_cache, item.link)

                #
                # SEND NOTIFICATION OUT
                #

                if 'notifications_sent' not in feed:
                    feed['notifications_sent'] = 1
                else:
                    feed['notifications_sent'] = feed['notifications_sent'] + 1

        feed['items_cached'] = r.scard(feed_cache)

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
        r.hset('feeds', feed_id, json.dumps(feed))


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

                feed_exists = r.hexists('feeds', feed_id)
                if feed_exists:
                    msg = {'errors': [{'title': 'Conflict',
                                       'details': 'A feed for this given URL already exists.'}]}
                    return jsonify(msg), 409

                new_feed = {'id': feed_id, 'url': feed['url'],
                            'fetch_interval_secs': feed['fetch_interval_secs'],
                            'webhook': feed['webhook']}

                app.logger.debug("creating " + json.dumps(new_feed))

                r.hset('feeds', feed_id, json.dumps(new_feed))

                try:

                    update_feed(feed_id)

                    scheduler.add_job(update_feed, 'interval',
                                      seconds=int(feed['fetch_interval_secs']),
                                      args=[new_feed['id']], id=feed_id)

                except Exception as e:
                    app.logger.error(e)
                    r.hdel('feeds', feed_id)


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
    for feed_id in r.hkeys('feeds'):
        feed = json.loads(r.hget('feeds', feed_id))
        feeds.append(feed)

    data = {'data': {'feeds': feeds}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>')
def return_feed_info(feed_id):
    feed_exists = r.hexists('feeds', feed_id)
    if not feed_exists:
        msg = {'errors': [{'title': 'Not found',
                           'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    # get the feed info and all the current items
    feed = json.loads(r.hget('feeds', feed_id))

    items = []
    for item in r.smembers("feed_%s_items" % feed_id):
        items.append(json.loads(item))

    data = {'data': {'feed': feed, 'feed_last_items': items}}
    response = jsonify(data)
    return response


@app.route('/feeds/<feed_id>', methods=['DELETE'])
def stop_watching_feed(feed_id):
    feed_exists = r.hexists('feeds', feed_id)
    if not feed_exists:
        msg = {'errors': [{'title': 'Not found',
                           'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    # unschedule the job related to this feed
    scheduler.remove_job(feed_id)

    # delete the feed
    r.hdel('feeds', feed_id)

    # remove all additional data related to this feed
    r.delete("feed_%s_items" % feed_id)
    r.delete("feed_%s_cache" % feed_id)


@app.route('/redis/info')
def get_redis_info():
    # return metrics about redis
    data = {'data': {'info': r.info()}}
    response = jsonify(data)
    return response


def initialize():
    scheduler.start()

    # recreate any jobs if needed
    for feed_id in r.hkeys('feeds'):
        feed = json.loads(r.hget('feeds', feed_id))

        scheduler.add_job(update_feed, 'interval', seconds=int(feed['fetch_interval_secs']),
                          args=[feed['id']], id=feed['id'])


if __name__ == "__main__":
    initialize()
    app.run(debug=True, port=8080, threaded=True)
    # app.run(port=8080, threaded=True)
