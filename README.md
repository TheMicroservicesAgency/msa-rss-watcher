
# msa-rss-watcher

Microservice to watch RSS or Atom feeds, and trigger notifications via webhooks for new items.

Built using [feedparser](https://pypi.python.org/pypi/feedparser).

## Quick start

Execute the microservice container with the following command :

    docker run -ti -p 9010:80 msagency/msa-rss-watcher

## Example(s)

To create a new watch for a given feed, you only have to specify the feed URL, how often to fetch updates,
 and where to send new items notifications - the webhook.

    $ curl -X POST "http://localhost:9910/feeds" -H "Content-Type: application/json" -d '{
        "feed" : {
            "url" : "http://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "refresh_secs": 30,
            "webhook": "http://requestb.in/1mshtpk1"
        }
    }'

    {
      "data": {
        "feed": {
          "id": "12fd97",
          "refresh_secs": 30,
          "url": "http://rss.nytimes.com/services/xml/rss/nyt/World.xml",
          "webhook": "https://httpbin.org/post"
        }
      }
    }

If the feed creation is sucessful you will get back the created feed definition, containing a unique ID.
The ID is the 6 first chars of the SHA256 signature of the feed URL.

In this example the NYTimes RSS feed willl be polled every 30 seconds, and new items will trigger a
POST request to http://requestb.in/1mshtpk1 - a JSON doc containing the item link, title, summary and published time.
Example:

    {  
       "data":{  
          "summary":"A worker on the outside wall of the Reactor 2 building at the Fukushima Daiichi Nuclear Power Station last month.",
          "title":"Struggling With Japan\u2019s Nuclear Waste, Six Years After Disaster",
          "published":"2017-03-11T21:00:31Z",
          "link":"http://www.nytimes.com/2017/03/11/world/asia/struggling-with-japans-nuclear-waste-six-years-after-disaster.html?partner=rss&emc=rss"
       }
    }

To see the full of watched feeds, simply do a HTTP GET request :

    $ curl "http://localhost:9910/feeds"

    {
      "data": {
        "feeds": [
          {
            "id": "12fd97",
            "items_cached": 12,
            "items_fetched": 24,
            "notifications_sent": 12,
            "refresh_secs": 30,
            "time_first_fetch": "2017-03-12T18:18:57.597617Z",
            "time_last_fetch": "2017-03-12T18:19:28.071164Z",
            "url": "http://rss.nytimes.com/services/xml/rss/nyt/World.xml",
            "webhook": "https://httpbin.org/post"
          }
        ]
      }
    }

To see the last items fetched for a given feed, specify the feed ID :

    $ curl "http://localhost:9910/feeds/12fd97"

    {
      "data": {
        "feed": {
          "id": "12fd97",
          "items_cached": 12,
          "items_fetched": 24,
          "notifications_sent": 12,
          "refresh_secs": 30,
          "time_first_fetch": "2017-03-12T18:18:57.597617Z",
          "time_last_fetch": "2017-03-12T18:19:28.071164Z",
          "url": "http://rss.nytimes.com/services/xml/rss/nyt/World.xml",
          "webhook": "https://httpbin.org/post"
        },
        "feed_last_items": [
          {
            "link": "http://www.nytimes.com/2017/03/12/business/dealbook/china-deals-capital-controls-hollywood.html?partner=rss&emc=rss",
            "published": "2017-03-12T14:53:44Z",
            "summary": "Zhong Shan, China\u2019s commerce minister, castigated what he called \u201cblind and irrational investment,\u201d at a briefing during the annual meeting of the country\u2019s congress.",
            "title": "After $225 Billion in Deals Last Year, China Reins In Overseas Investment"
          },
          {
            "link": "http://www.nytimes.com/2017/03/12/world/europe/russia-hacker-evgeniy-bogachev.html?partner=rss&emc=rss",
            "published": "2017-03-12T14:51:08Z",
            "summary": "Evgeniy M. Bogachev. The F.B.I. has offered a $3 million bounty for his capture, the most ever for a cybercriminal.",
            "title": "Russian Espionage Piggybacks on a Cybercriminal\u2019s Hacking"
          },
         ...

To stop watching a feed send a HTTP DELETE with the feed ID.

    $ curl -XDELETE http://localhost:9910/feeds/12fd97

    {
      "data": {
        "feed": {
          "id": "12fd97",
          "items_cached": 12,
          "items_fetched": 48,
          "notifications_sent": 12,
          "refresh_secs": 30,
          "time_first_fetch": "2017-03-12T18:18:57.597617Z",
          "time_last_fetch": "2017-03-12T18:20:29.663288Z",
          "url": "http://rss.nytimes.com/services/xml/rss/nyt/World.xml",
          "webhook": "https://httpbin.org/post"
        }
      }
    }

    $ curl http://localhost:9910/feeds

    {
      "data": {
        "feeds": []
      }
    }

## Endpoints

- POST [/feeds]() : watches a new feed for new updates
- GET [/feeds](/feeds) : returns the list of currently watched feeds
- GET [/feeds/:id]() : get last items fetched of a given feed
- DELETE [/feeds/:id]() : stop watching the given RSS feed

## Standard endpoints

- GET [/ms/version](/ms/version) : returns the version number
- GET [/ms/name](/ms/name) : returns the name
- GET [/ms/readme.md](/ms/readme.md) : returns the readme (this file)
- GET [/ms/readme.html](/ms/readme.html) : returns the readme as html
- GET [/swagger/swagger.json](/swagger/swagger.json) : returns the swagger api documentation
- GET [/swagger/#/](/swagger/#/) : returns swagger-ui displaying the api documentation
- GET [/nginx/stats.json](/nginx/stats.json) : returns stats about Nginx
- GET [/nginx/stats.html](/nginx/stats.html) : returns a dashboard displaying the stats from Nginx

## About

A project by the [Microservices Agency](http://microservices.agency).
