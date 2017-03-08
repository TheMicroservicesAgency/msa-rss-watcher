from flask import Flask, jsonify, request
from apscheduler.schedulers.background import BackgroundScheduler
import feedparser
import maya
from tinydb import TinyDB
from tinydb import where
from tinydb.storages import MemoryStorage
import hashlib
import json
from pybloom import ScalableBloomFilter
import pickle
import codecs
import sys


scheduler = BackgroundScheduler() # create the in-memory scheduler

db = TinyDB(storage=MemoryStorage) # initialize the in-memory database

app = Flask(__name__) # initialize the Flask app


@app.before_first_request
def initialize():
    scheduler.start()

# from http://stackoverflow.com/questions/1094841/reusable-library-to-get-human-readable-version-of-file-size
def human_readable_bytes(num):
    for unit in ['B','KiB','MiB','GiB','TiB','PiB','EiB','ZiB']:
        if abs(num) < 1024.0:
            return "%3.1f %s" % (num, unit)
        num /= 1024.0
    return "%.1f %s" % (num, 'Yi')


def update_feed(feed_id):
    with app.app_context():

        app.logger.debug("updating " + json.dumps(feed_id))

        # get the feed data from the db
        feed_data = db.table('feeds').search(where('id') == feed_id)[0]

        # fetch the feed items, this involves an external HTTP request
        data = feedparser.parse(feed_data['url'])
        feed_update_time = maya.now().iso8601()

        app.logger.debug("got %s items " % len(data.entries))

        # get the bloom filter for this feed, useful to exclude previously seen items
        # see https://en.wikipedia.org/wiki/Bloom_filter
        # and https://blog.medium.com/what-are-bloom-filters-1ec2a50c68ff
        results = db.table('feeds_bloom_filters').search(where('id') == feed_id)
        if len(results) == 1:
            app.logger.debug("loading existing sbf")
            pickled_sbf = results[0]['bloom_filter']

            # base64 is certainly not the most efficient storage format but I'm not sure TinyDB handles binary data
            sbf = pickle.loads(codecs.decode(pickled_sbf.encode(), "base64"))
        else:
            app.logger.debug("creating new sbf")

            # from the module doc: Scalable Bloom Filters allow your bloom filter bits to grow as a function of
            # false positive probability and size. When capacity is reached a new filter is then created exponentially
            # larger than the last with a tighter probability of false positives and a larger number of hash functions.
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

            # check if we have seen this item before
            if item.link not in sbf:
                app.logger.debug("new item => " + item.link)

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
            app.logger.debug("updating sbf in db")
            db.table('feeds_bloom_filters').update(bloom_filter, where('id') == feed_id)
        else:
            app.logger.debug("inserting sbf in db")
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

        # add some debugging info
        feed_data['sbloom_filter_capacity'] = sbf.capacity
        feed_data['sbloom_filter_error_rate'] = sbf.error_rate
        feed_data['sbloom_filter_size_bytes'] = sys.getsizeof(pickled_sbf)
        feed_data['sbloom_filter_size_human'] = human_readable_bytes(sys.getsizeof(pickled_sbf))

        # update the feed data in the db
        db.table('feeds').update(feed_data, where('id') == feed_id)


@app.route('/feeds', methods=['POST'])
def watch_new_feed():

    try:
        data = request.json

        if 'feed' in data:

            feed = data['feed']

            if 'url' in feed and 'update_interval_secs' in feed and 'webhook' in feed:

                # generate an ID for this new feed
                m = hashlib.sha256()
                m.update(str.encode(feed['url']))
                id = m.hexdigest()[0:6]

                new_feed = {'id': id, 'url': feed['url'], 'update_interval_secs': feed['update_interval_secs'],
                            'webhook': feed['webhook']}

                app.logger.debug("creating " + json.dumps(new_feed))

                feeds = db.table('feeds')
                feeds.insert(new_feed)

                scheduler.add_job(update_feed, 'interval', seconds=int(feed['update_interval_secs']),
                                  args=[new_feed['id']], id=id)


    except Exception as e:
        app.logger.error(e)
        msg = {'errors': [{'title': 'Could not parse feed', 'details': ''}]}
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
    results = feeds.search(where('id') == id)

    if len(results) == 0:
        msg = {'errors': [{'title': 'Not found', 'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    feed = results[0]
    feed_items_table = "feed_%s_items" % id
    feed_items = db.table(feed_items_table)

    data = {'data': {'feed': feed, 'feed_items': feed_items.all()}}
    response = jsonify(data)
    return response


@app.route('/feeds/<id>', methods=['DELETE'])
def stop_watching_feed(id):


    feeds = db.table('feeds')
    results = feeds.search(where('id') == id)

    if len(results) == 0:
        msg = {'errors': [{'title': 'Not found', 'details': 'Could not find a feed with the specified ID'}]}
        return jsonify(msg), 404

    if len(results) == 1:
        feed = results[0]
        feeds.remove(eids=[feed.eid])

    # unschedule the job related to this feed

    scheduler.remove_job(id)

    # remove all additional data related to this feed from the db

    db.purge_table("feed_%s_items" % id)

    bfs = db.table('feeds_bloom_filters')
    results = bfs.search(where('id') == id)

    if len(results) == 1:
        bf = results[0]
        bfs.remove(eids=[bf.eid])




if __name__ == "__main__":

    app.run(debug=True, port=8080, threaded=True)
    # app.run(port=8080, threaded=True)
