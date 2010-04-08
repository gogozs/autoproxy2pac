# -*- coding: utf-8 -*-

from google.appengine.ext import webapp
from google.appengine.api import memcache
from django.utils.feedgenerator import DefaultFeed as Feed

from models import RuleList, ChangeLog
from util import template, webcached

def getSampleUrlFromRule(rule):
    from urllib import unquote
    rule = unquote(rule.encode())
    try:
        rule = rule.decode('utf-8', 'strict')
    except UnicodeDecodeError:
        rule = rule.decode('gbk', 'ignore')
    if rule.startswith('||'): return 'http://' + rule[2:]
    if rule.startswith('.'): return 'http://' + rule[1:]
    if rule.startswith('|'): return rule[1:]
    rule = rule.replace('wikipedia.org*', 'wikipedia.org/wiki/')
    if not rule.startswith('http'): return 'http://' + rule
    return rule

def generateLogFromDiff(diff):
    from collections import defaultdict
    urlStatus = defaultdict(lambda:{True:[], False:[]})
    log = {'timestamp':diff.date, 'block':[], 'unblock':[], 'rule_adjust':[]}

    for type in ('add', 'remove'):
        blocked = type == 'add'
        for rule in getattr(diff, type):
            if rule.startswith('@@'):
                url = getSampleUrlFromRule(rule[2:])
                log['rule_adjust'].append({'from':(), 'to':(rule,), 'sample_url':url})
            else:
                url = getSampleUrlFromRule(rule)
                urlStatus[url][blocked].append(rule)

    for url, status in urlStatus.items():
        if status[True] and not status[False]:
            log['block'].append({'rules':status[True], 'sample_url':url})
        elif not status[True] and status[False]:
            log['unblock'].append({'rules':status[False], 'sample_url':url})
        else:
            log['rule_adjust'].append({'from':status[False], 'to':status[True], 'sample_url':url})

    return log

class FeedHandler(webapp.RequestHandler):
    @webcached()
    def get(self, name):
        name = name.lower()
        rules = RuleList.getList(name)
        if rules is None:
            self.error(404)
            return

        # Conditional redirect to FeedBurner
        # @see: http://www.google.com/support/feedburner/bin/answer.py?hl=en&answer=78464
        if(self.request.get('raw', None) is None and        # http://host/path/name.rss?raw
           'FeedBurner' not in self.request.user_agent):    # FeedBurner fetcher
            self.redirect('http://feeds.feedburner.com/%s' % name, permanent=False)
            return

        self.lastModified(rules.date)

        start = int(self.request.get('start', 0))
        fetchNum = start + int(self.request.get('num', 20))
        if fetchNum > 1000:
            self.error(412)
            return

        logs = memcache.get('changelog/%s' % name)
        if logs is None or len(logs) < fetchNum:
            diff = ChangeLog.gql("WHERE ruleList = :1 ORDER BY date DESC", rules).fetch(fetchNum)
            logs = map(generateLogFromDiff, diff)
            memcache.add('changelog/%s' % name, logs)

        self.response.headers['Content-Type'] = Feed.mime_type

        f = Feed(title="%s 更新记录" % name,
                 link=self.request.relative_url(name),
                 description="beta",
                 language="zh")

        for item in logs:
            f.add_item(title="%d月%d日 %s 更新: 增加 %d 条, 删除 %d 条" % (item['timestamp'].month, item['timestamp'].day, name, len(item['block']), len(item['unblock'])),
                       link='',
                       description=template.render('changelogRssItem.html', **item),
                       author_name="gfwlist",
                       pubdate=item['timestamp'])

        f.write(self.response.out, 'utf-8')
