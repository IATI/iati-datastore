from iatilib import log
from iatilib import session
from iatilib.model import *
from iatilib.frontend import app
from flask import request, make_response, escape
from datetime import datetime,timedelta
import json
import functools
from urllib import urlencode

##################################################
####           Utilities
##################################################

all_endpoints = []

def endpoint(rule, **options):
    """Function decorator borrowed & modified from Flask core."""
    BASE='/api/1'
    def decorator(f):
        @functools.wraps(f)
        def wrapped_fn_xml(*args, **kwargs):
            callback = request.args.get('callback')
            try:
                raw = f(*args, **kwargs)
            except (AssertionError, ValueError) as e:
                if request.args.get('_debug') is not None:
                    raise e
                raw = { 'ok': False, 'message' : e.message }
            response = make_response(raw)
            response.headers['content-type'] = 'text/xml'
            return response
        @functools.wraps(f)
        def wrapped_fn_csv(*args, **kwargs):
            try:
                raw = f(*args, **kwargs) 
                assert type(raw) is list, type(raw)
            except (AssertionError, ValueError) as e:
                if request.args.get('_debug') is not None:
                    raise e
                raw = [{ 'ok': False, 'message' : e.message }]
            csv_headers = []
            for x in raw: csv_headers += x.keys()
            csv_headers = list(set(csv_headers))
            response_text = ','.join(csv_headers) + '\n'
            for x in raw:
                response_text += ','.join( [str(x.get(key) or '') for key in csv_headers ] ) + '\n'
            response = make_response(response_text)
            response.headers['content-type'] = 'text/csv'
            return response
        @functools.wraps(f)
        def wrapped_fn_json(*args, **kwargs):
            callback = request.args.get('callback')
            try:
                results = f(*args, **kwargs) 
                raw = {
                        'ok': True, 
                        'num_results': len(results), 
                        'results' :results
                      }
            except (AssertionError, ValueError) as e:
                if request.args.get('_debug') is not None:
                    raise e
                raw = { 'ok': False, 'message' : e.message }
            response_text = json.dumps(raw)
            if callback:
                response_text = '%s(%s);' % (callback,response_text)
            response = make_response(response_text)
            response.headers['content-type'] = 'application/json'
            return response
        endpoint = options.pop('endpoint', BASE+rule)
        # Add this endpoint to the list
        all_endpoints.append(BASE+rule)
        # Bind to the root, JSON and CSV endpoints simultaneously
        app.add_url_rule(BASE+rule+'.json', endpoint+'.json', wrapped_fn_json, **options)
        app.add_url_rule(BASE+rule+'.xml', endpoint+'.xml', wrapped_fn_xml, **options)
        app.add_url_rule(BASE+rule+'.csv', endpoint+'.csv', wrapped_fn_csv, **options)
        app.add_url_rule(BASE+rule, endpoint, wrapped_fn_json, **options)
        return f
    return decorator

def json_obj(obj):
    keys = filter(lambda x:x[0]!='_', dir(obj))
    keys.remove('metadata')
    out = { x: getattr(obj,x) for x in keys }
    return out

###########################################
####   IATI argument parser 
###########################################

def parse_args():
    """Turn the querystring into an XPath expression we can use to select elements.
    See the querystring section of the IATI document:
    https://docs.google.com/document/d/1gxvmYZSDXBTSMAU16bxfFd-hn1lYVY1c2olkXbuPBj4/edit
    Plenty of special cases apply!
    """
    def clean_parent(parent, child, property):
        if parent:
            return parent+'/'
        return ''
    def clean_child(parent, child, property):
        if child=='sector':
            return 'sector[@vocabulary=\'DAC\']'
        return child
    def clean_property(parent, child, property):
        if property=='text':
            return '/text()'
        if property:
            return '/@'+property
        if child=='sector' \
                or child=='recipient-country':
            return '/@code'
        if child=='participating-org'\
                or child=='reporting-org':
            return '/@ref'
        return '/text()'
    def split(key):
        # Split out the parent xPath element
        split_parent = key.split('_')
        assert len(split_parent)<=2, 'Bad parameter: %s' % key
        xParent = split_parent[0] if len(split_parent)==2 else None
        # Split out the child xPath element
        split_child = split_parent[-1].split('.')
        assert len(split_child)<=2, 'Bad parameter: %s' % key
        xChild = split_child[0]
        xProperty = split_child[1] if len(split_child)>1 else None
        return xParent, xChild, xProperty
    # Create an array of xpath strings...
    out = []
    for key,value in sorted(request.args.items(), key=lambda x:x[0]):
        xParent, xChild, xProperty = split(key)
        # Left hand side of the query's equals sign
        lhs = clean_parent(xParent,xChild,xProperty)\
                + clean_child(xChild,xChild,xProperty)\
                + clean_property(xProperty,xChild,xProperty) 
        # Nested OR groups within AND groups...
        _or      = lambda x : x[0] if len(x)==1 else '(%s)' % ' or '.join(x)
        _and     = lambda x : x[0] if len(x)==1 else '(%s)' % ' and '.join(x)
        or_string  = lambda x:  _or( [    lhs+'=\''+y+'\'' for y in x.split('|') ] )
        and_string = lambda x: _and( [ or_string(y) for y in x.split('+') ] )
        # input:   ?field=aa||bb+cc   
        # output:  ((field/text()=aa or field/text()=bb) and (field.text()=cc))
        out.append(and_string(value))
    return ' and '.join(out)




##################################################
####           URL: /
##################################################
@endpoint('/')
def index():
    # Root of the API lists all available endpoints
    rules = [x.rule for x in app.url_map.iter_rules()]
    #all_endpoints = [request.url_root[:-1]+x for x in rules if x.startswith('/api/1')]
    return {'version':'1.0','ok':True,'endpoints':all_endpoints}

#### URL: /about

@endpoint('/about')
def about():
    # General status info
    count_activity = session.query(Activity).count()
    count_transaction = session.query(Transaction).count()
    return {'ok':True,'status':'healthy','indexed_activities':count_activity,'indexed_transactions':count_transaction}

#### URL: /transaction and /transactions

@endpoint('/access/transactions')
def transaction_list():
    query = session.query(Transaction)
    query = query.limit(20)
    return [ json_obj(x) for x in query ]

@endpoint('/access/transaction/<id>')
def transaction(id):
    query = session.query(Transaction)\
            .filter(Transaction.iati_identifier==id)
    query = query.limit(20)
    return [ json_obj(x) for x in query ]

#### URL: /activity and /activities

@endpoint('/access/activities')
def activities_list():
    query = session.query(Activity)
    query = query.limit(20)
    return [ json_obj(x) for x in query ]

@endpoint('/access/activity/<id>')
def activity(id):
    query = session.query(Activity)\
            .filter(Activity.iati_identifier==id)
    return [ json_obj(x) for x in query ]

## @endpoint('/debug/args')
## def debug_args():
##     return {'raw':request.args, 'processed':parse_args()}


