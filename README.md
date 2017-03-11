
# msa-rss-watcher

Microservice to watch RSS or Atom feeds, and trigger notifications via webhooks for new items.

Built using [feedparser](https://pypi.python.org/pypi/feedparser).

## Quick start

Execute the microservice container with the following command :

    docker run -ti -p 9010:80 msagency/msa-rss-watcher

## Example(s)





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
