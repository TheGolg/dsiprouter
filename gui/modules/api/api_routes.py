import os, re, json, time, pipes, subprocess
import urllib.parse as parse
from functools import wraps
from flask import Blueprint, jsonify
from flask import Blueprint, session, render_template,jsonify
from flask import Flask, render_template, request, redirect, abort, flash, session, url_for, send_from_directory,send_file
from sqlalchemy import case, func, exc as sql_exceptions, and_, not_
from werkzeug import exceptions as http_exceptions
from werkzeug.utils import secure_filename
from database import loadSession, Address, dSIPNotification, Domain, DomainAttrs, dSIPDomainMapping, \
    dSIPMultiDomainMapping, Dispatcher, Gateways, GatewayGroups, Subscribers, dSIPLeases, dSIPMaintModes, \
    dSIPCallLimits, InboundMapping, dSIPCDRInfo
from datetime import datetime
from shared import *
from util.notifications import sendEmail
from file_handling import isValidFile
import settings, globals,random


db = loadSession()
api = Blueprint('api', __name__)

# TODO: we need to standardize our response payload
# preferably we can create a custom response class

def checkDatabase():
   # Check database connection is still good
    try:
        db.execute('select 1')
        db.flush()
    except sql_exceptions.SQLAlchemyError as ex:
    # If not, close DB connection so that the SQL engine can get another one from the pool
        db.close()
        global db
        db = loadSession()


class APIToken:
    token = None

    def __init__(self, request):
        if 'Authorization' in request.headers:
            auth_header = request.headers.get('Authorization')
            if auth_header:
                self.token = auth_header.split(' ')[1]

    def isValid(self):
        if self.token:
            return settings.DSIP_API_TOKEN == self.token
        else:
            return False


def api_security(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        # List of User Agents that are text based
        TextUserAgentList = ['curl', 'http_async_client']
        consoleUserAgent = False
        apiToken = APIToken(request)

        if not session.get('logged_in') and not apiToken.isValid():
            user_agent = request.headers.get('User-Agent')
            if user_agent is not None:
                for agent in TextUserAgentList:
                    if agent in user_agent:
                        consoleUserAgent = True
                        pass
            if consoleUserAgent:
                msg = '{"error": "Unauthorized", "error_msg": "Invalid Token"}\n'
                return Response(msg, 401)
            else:
                return render_template('index.html', version=settings.VERSION)
        return func(*args, **kwargs)

    return wrapper

@api.route("/api/v1/kamailio/stats", methods=['GET'])
@api_security
def getKamailioStats():
    try:
        if (settings.DEBUG):
            debugEndpoint()

        payload = {"jsonrpc": "2.0", "method": "tm.stats","id": 1}
        #r = requests.get('https://www.google.com',data=payload)
        r = requests.get('http://127.0.0.1:5060/api/kamailio',json=payload)
        #print(r.text)

        return r.text

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "db"
        db.rollback()
        db.flush()
        return showError(type=error)
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return showError(type=error)
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        db.rollback()
        db.flush()
        return showError(type=error)


@api.route("/api/v1/kamailio/reload", methods=['GET'])
@api_security
def reloadKamailio():
    try:
        if (settings.DEBUG):
            debugEndpoint()

        payloadResponse = {}
        configParameters = {}
        #TODO: Get the configuration parameters to be updatable via the API
        #configParameters['cfg.sets:teleblock-gw_up'] = 'teleblock, gw_ip' + str(settings.TELEBLOCK_GW_IP)
        #configParameters['cfg.sets:teleblock-media_ip'] ='"teleblock", "media_ip",' +  str(settings.TELEBLOCK_MEDIA_IP)
        #configParameters['cfg.seti:teleblock-gw_enabled'] ='"teleblock", "gw_enabled",' +  str(settings.TELEBLOCK_GW_ENABLED)
        #configParameters['cfg.seti:teleblock-gw_port'] ='"teleblock", "gw_port",' +  str(settings.TELEBLOCK_GW_PORT)
        #configParameters['cfg.seti:teleblock-media_port'] ='"teleblock", "gw_media_port,' +  str(settings.TELEBLOCK_MEDIA_PORT)

        reloadCommands = [
            {"method": "permissions.addressReload", "jsonrpc": "2.0", "id": 1},
            {'method': 'drouting.reload', 'jsonrpc': '2.0', 'id': 1},
            {'method': 'domain.reload', 'jsonrpc': '2.0', 'id': 1},
            {'method': 'dispatcher.reload', 'jsonrpc': '2.0', 'id': 1},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["tofromprefix"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["maintmode"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["calllimit"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["gw2gwgroup"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["inbound_hardfwd"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["inbound_failfwd"]},
            {'method': 'htable.reload', 'jsonrpc': '2.0', 'id': 1, 'params': ["inbound_prefixmap"]},
            {'method': 'uac.reg_reload', 'jsonrpc': '2.0', 'id': 1}
        ]

        for cmdset in reloadCommands:
            r = requests.get('http://127.0.0.1:5060/api/kamailio', json=cmdset)
            payloadResponse[cmdset['method']] = r.status_code


        #for key in configParameters:
        #    if "cfgs.sets" in key:
        #        payload = '{{"jsonrpc": "2.0", "method": "cfg.sets", "params" : [{}],"id": 1}}'.format(key,configParameters[key])
        #    elif "cfgi.seti" in key:
        #        payload = '{{"jsonrpc": "2.0", "method": "cfg.seti", "params" : {},"id": 1}}'.format(key,configParameters[key])
        #
        #    r = requests.get('http://127.0.0.1:5060/api/kamailio',json=payload)
        #   payloadResponse[key]=json.dumps({"status":r.status_code,"message":r.json()})
        #    payloadResponse[key]=r.status_code

        globals.reload_required = False
        return json.dumps({"results": payloadResponse})

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "db"
        db.rollback()
        db.flush()
        return showError(type=error)
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return showError(type=error)
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        db.rollback()
        db.flush()
        return showError(type=error)


@api.route("/api/v1/endpoint/lease", methods=['GET'])
@api_security
def getEndpointLease():
    try:
        if (settings.DEBUG):
            debugEndpoint()

        email=request.args.get('email')
        if not email:
            raise Exception("email parameter is missing")

        ttl=request.args.get('ttl')
        if not ttl:
            raise Exception("time to live (ttl) parameter is missing")

        # Generate some values
        rand_num= random.randint(1,200)
        name = "lease" + str(rand_num)
        auth_username = name
        auth_password = generatePassword()
        auth_domain = settings.DOMAIN
        if settings.DSIP_API_HOST:
            api_hostname = settings.DSIP_API_HOST
        else:
            api_hostname = getExternalIP()

        #Set some defaults
        ip_addr =''
        strip=''
        prefix=''

        #Add the Gateways table

        Gateway = Gateways(name, ip_addr, strip, prefix, settings.FLT_PBX)
        db.add(Gateway)
        db.flush()

        #Add the Subscribers table

        Subscriber = Subscribers(auth_username, auth_password, auth_domain, Gateway.gwid, email)
        db.add(Subscriber)
        db.flush()

        #Add to the Leases table

        Lease = dSIPLeases(Gateway.gwid, Subscriber.id, int(ttl))
        db.add(Lease)
        db.flush()

        payload = {}
        payload['leaseid'] = Lease.id
        payload['username'] = auth_username
        payload['password'] = auth_password
        payload['hostname'] = api_hostname
        payload['domain'] = auth_domain
        payload['ttl'] = ttl

        #Commit transactions to database

        db.commit()
        return json.dumps(payload)

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "db"
        #db.rollback()
        #db.flush()
        return showError(type=error)
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        #db.rollback()
        #db.flush()
        return showError(type=error)
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        #db.rollback()
        #db.flush()
        return showError(type=error)

@api.route("/api/v1/endpoint/lease/<int:leaseid>/revoke", methods=['PUT'])
@api_security
def revokeEndpointLease(leaseid):
    try:
        if (settings.DEBUG):
            debugEndpoint()

        # Query the Lease ID
        Lease = db.query(dSIPLeases).filter(dSIPLeases.id == leaseid).first()

        # Remove the entry in the Subscribers table

        Subscriber = db.query(Subscribers).filter(Subscribers.id == Lease.sid).first()
        db.delete(Subscriber)
        # Remove the entry in the Gateway table

        Gateway = db.query(Gateways).filter(Gateways.gwid == Lease.gwid).first()
        db.delete(Gateway)

        # Remove the entry in the Lease table

        db.delete(Lease)

        payload = {}
        payload['leaseid'] = leaseid
        payload['status'] = 'revoked'

        db.commit()
        return json.dumps(payload)

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "db"
        db.rollback()
        db.flush()
        return showError(type=error)
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return showError(type=error)
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        db.rollback()
        db.flush()
        return showError(type=error)

class APIException(Exception):
    pass

class MaintModeAttrMissing(APIException):
    pass

@api.route("/api/v1/endpoint/<int:id>", methods=['POST'])
@api_security
def updateEndpoint(id):
    try:
        if (settings.DEBUG):
            debugEndpoint()

        # Define a dictionary object that represents the payload
        responsePayload = {}

        # Set the status to 0, update it to 1 if the update is successful
        responsePayload['status'] = 0

        # Covert JSON message to Dictionary Object
        requestPayload = request.get_json()

        # Only handling the maintmode attribute on this release
        try:
             if 'maintmode' not in requestPayload:
                 raise MaintModeAttrMissing

             if requestPayload['maintmode'] == 0:
                 MaintMode = db.query(dSIPMaintModes).filter(dSIPMaintModes.gwid == id).first()
                 if MaintMode:
                     db.delete(MaintMode)
             elif requestPayload['maintmode'] == 1:
                #Lookup Gateway ip adddess
                 Gateway = db.query(Gateways).filter(Gateways.gwid == id).first()
                 db.commit()
                 db.flush()
                 if Gateway != None:
                     MaintMode = dSIPMaintModes(Gateway.address,id)
                 db.add(MaintMode)
        except MaintModeAttrMissing as ex:
            responsePayload['error'] = "maintmode attribute is missing"
            return json.dumps(responsePayload)

        db.commit()
        responsePayload['status'] = 1

        return json.dumps(responsePayload)

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "db"
        db.rollback()
        db.flush()
        if isinstance(ex, sql_exceptions.IntegrityError):
            responsePayload['error'] = "endpoint {} is already in maintmode".format(id)
        return json.dumps(responsePayload)
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return json.dumps(responsePayload)
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        db.rollback()
        db.flush()
        return json.dumps(responsePayload)

# TODO: we should obviously optimize this and cleanup reused code
@api.route("/api/v1/inboundmapping", methods=['GET', 'POST', 'PUT', 'DELETE'])
@api_security
def handleInboundMapping():
    """
    Endpoint for Inbound DID Rule Mapping
    """

    # dr_routing prefix matching supported characters
    # refer to: <https://kamailio.org/docs/modules/5.1.x/modules/drouting.html#idp26708356>
    # TODO: we should move this somewhere shared between gui and api
    PREFIX_ALLOWED_CHARS = {'0','1','2','3','4','5','6','7','8','9','+','#','*'}

    # use a whitelist to avoid possible SQL Injection vulns
    VALID_REQUEST_ARGS = {'ruleid', 'did'}

    # use a whitelist to avoid possible buffer overflow vulns or crashes
    VALID_REQUEST_DATA_ARGS = {'did', 'servers', 'name'}

    # defaults.. keep data returned seperate from returned metadata
    payload = {'error': None, 'msg': '', 'kamreload': globals.reload_required, 'data': []}

    try:
        if (settings.DEBUG):
            debugEndpoint()

        # =========================================
        # get rule for DID mapping or list of rules
        # =========================================
        if request.method == "GET":
            # sanity check
            for arg in request.args:
                if arg not in VALID_REQUEST_ARGS:
                    raise http_exceptions.BadRequest("Request argument not recognized")

            # get single rule by ruleid
            rule_id = request.args.get('ruleid')
            if rule_id is not None:
                res = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.ruleid == rule_id).first()
                if res is not None:
                    data = rowToDict(res)
                    data = {'ruleid': data['ruleid'], 'did': data['prefix'], 'name': strFieldsToDict(data['description'])['name'], 'servers': data['gwlist'].split(',')}
                    payload['data'].append(data)
                    payload['msg'] = 'Rule Found'
                else:
                    payload['msg'] = 'No Matching Rule Found'

            # get single rule by did
            else:
                did_pattern = request.args.get('did')
                if did_pattern is not None:
                    res = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.prefix == did_pattern).first()
                    if res is not None:
                        data = rowToDict(res)
                        data = {'ruleid': data['ruleid'], 'did': data['prefix'], 'name': strFieldsToDict(data['description'])['name'], 'servers': data['gwlist'].split(',')}
                        payload['data'].append(data)
                        payload['msg'] = 'DID Found'
                    else:
                        payload['msg'] = 'No Matching DID Found'

                # get list of rules
                else:
                    res = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).all()
                    if len(res) > 0:
                        for row in res:
                            data = rowToDict(row)
                            data = {'ruleid': data['ruleid'], 'did': data['prefix'], 'name': strFieldsToDict(data['description'])['name'], 'servers': data['gwlist'].split(',')}
                            payload['data'].append(data)
                        payload['msg'] = 'Rules Found'
                    else:
                        payload['msg'] = 'No Rules Found'

            return json.dumps(payload), status.HTTP_OK

        # ===========================
        # create rule for DID mapping
        # ===========================
        elif request.method == "POST":
            # TODO: should we enforce strict mimetype matching?
            data = request.get_json(force=True)

            # sanity checks
            for arg in data:
                if arg not in VALID_REQUEST_DATA_ARGS:
                    raise http_exceptions.BadRequest("Request data argument not recognized")

            if 'servers' not in data:
                raise http_exceptions.BadRequest('Servers to map DID to are required')
            elif len(data['servers']) < 1 or len(data['servers']) > 2:
                raise http_exceptions.BadRequest('Primary Server missing or More than 2 Servers Provided')
            elif 'did' not in data:
                raise http_exceptions.BadRequest('DID is required')

            # TODO: we should be checking dr_gateways table to make sure the servers exist
            for i in range(0, len(data['servers'])):
                try:
                    data['servers'][i] = str(data['servers'][i])
                    _ = int(data['servers'][i])
                except:
                    raise http_exceptions.BadRequest('Invalid Server ID')
            for c in data['did']:
                if c not in PREFIX_ALLOWED_CHARS:
                    raise http_exceptions.BadRequest('DID improperly formatted, allowed characters: {}'.format(','.join(PREFIX_ALLOWED_CHARS)))

            gwlist = ','.join(data['servers'])
            prefix = data['did']
            description = 'name:{}'.format(data['name']) if 'name' in data else ''

            # don't allow duplicate entries
            if db.query(InboundMapping).filter(InboundMapping.prefix == prefix).filter(InboundMapping.groupid == settings.FLT_INBOUND).scalar():
                raise http_exceptions.BadRequest("Duplicate DID's are not allowed")
            IMap = InboundMapping(settings.FLT_INBOUND, prefix, gwlist, description)
            db.add(IMap)

            db.commit()
            globals.reload_required = True
            payload['kamreload'] = globals.reload_required
            payload['msg'] = 'Rule Created'
            return json.dumps(payload), status.HTTP_OK

        # ===========================
        # update rule for DID mapping
        # ===========================
        elif request.method == "PUT":
            # sanity check
            for arg in request.args:
                if arg not in VALID_REQUEST_ARGS:
                    raise http_exceptions.BadRequest("Request argument not recognized")

            # TODO: should we enforce strict mimetype matching?
            data = request.get_json(force=True)
            updates = {}

            # sanity checks
            for arg in data:
                if arg not in VALID_REQUEST_DATA_ARGS:
                    raise http_exceptions.BadRequest("Request data argument not recognized")

            if 'did' not in data and 'servers' not in data and 'name' not in data:
                raise http_exceptions.BadRequest("No data args supplied, {did, and servers} is required")
            # TODO: we should be checking dr_gateways table to make sure the servers exist
            if 'servers' in data:
                if len(data['servers']) < 1 or len(data['servers']) > 2:
                    raise http_exceptions.BadRequest('Primary Server missing or More than 2 Servers Provided')
                else:
                    for i in range(0, len(data['servers'])):
                        try:
                            data['servers'][i] = str(data['servers'][i])
                            _ = int(data['servers'][i])
                        except:
                            raise http_exceptions.BadRequest('Invalid Server ID')
                updates['gwlist'] = ','.join(data['servers'])
            if 'did' in data:
                for c in data['did']:
                    if c not in PREFIX_ALLOWED_CHARS:
                        raise http_exceptions.BadRequest('DID improperly formatted, allowed characters: {}'.format(','.join(PREFIX_ALLOWED_CHARS)))
                updates['prefix'] = data['did']
            if 'name' in data:
                updates['description'] = 'name:{}'.format(data['name'])

            # update single rule by ruleid
            rule_id = request.args.get('ruleid')
            if rule_id is not None:
                res = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.ruleid == rule_id).update(
                    updates, synchronize_session=False)
                if res > 0:
                    payload['msg'] = 'Rule Updated'
                else:
                    payload['msg'] = 'No Matching Rule Found'

            # update single rule by did
            else:
                did_pattern = request.args.get('did')
                if did_pattern is not None:
                    res = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.prefix == did_pattern).update(
                        updates, synchronize_session=False)
                    if res > 0:
                        payload['msg'] = 'Rule Updated'
                    else:
                        payload['msg'] = 'No Matching Rule Found'

                # no other options
                else:
                    raise http_exceptions.BadRequest('One of the following is required: {ruleid, or did}')

            db.commit()
            globals.reload_required = True
            payload['kamreload'] = globals.reload_required
            return json.dumps(payload), status.HTTP_OK

        # ===========================
        # delete rule for DID mapping
        # ===========================
        elif request.method == "DELETE":
            # sanity check
            for arg in request.args:
                if arg not in VALID_REQUEST_ARGS:
                    raise http_exceptions.BadRequest("Request argument not recognized")

            # delete single rule by ruleid
            rule_id = request.args.get('ruleid')
            if rule_id is not None:
                rule = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.ruleid == rule_id)
                rule.delete(synchronize_session=False)

            # delete single rule by did
            else:
                did_pattern = request.args.get('did')
                if did_pattern is not None:
                    rule = db.query(InboundMapping).filter(InboundMapping.groupid == settings.FLT_INBOUND).filter(InboundMapping.prefix == did_pattern)
                    rule.delete(synchronize_session=False)

                # no other options
                else:
                    raise http_exceptions.BadRequest('One of the following is required: {ruleid, or did}')

            db.commit()
            globals.reload_required = True
            payload['kamreload'] = globals.reload_required
            payload['msg'] = 'Rule Deleted'
            return json.dumps(payload), status.HTTP_OK

        # not possible
        else:
            raise Exception('Unknown Error Occurred')

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        payload['error'] = "db"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        db.rollback()
        db.flush()
        return json.dumps(payload), status_code
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        payload['error'] = "http"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = ex.code or status.HTTP_INTERNAL_SERVER_ERROR
        db.rollback()
        db.flush()
        return json.dumps(payload), status_code
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        payload['error'] = "server"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        db.rollback()
        db.flush()
        return json.dumps(payload), status_code

@api.route("/api/v1/notification/gwgroup", methods=['POST'])
@api_security
def handleNotificationRequest():
    """
    Endpoint for Sending Notifications
    """

    # use a whitelist to avoid possible buffer overflow vulns or crashes
    VALID_REQUEST_DATA_ARGS = {'gwgroupid': int, 'type': int, 'text_body': str,
                               'gwid': int, 'subject': str, 'sender': str}

    # defaults.. keep data returned seperate from returned metadata
    payload = {'error': None, 'msg': '', 'kamreload': globals.reload_required, 'data': []}

    try:
        if (settings.DEBUG):
            debugEndpoint()

        # ============================
        # create and send notification
        # ============================

        content_type = str.lower(request.headers.get('Content-Type'))
        if 'multipart/form-data' in content_type:
            data = request.form.to_dict(flat=False)
        elif 'application/x-www-form-urlencoded' in content_type:
            data = request.form.to_dict(flat=False)
        else:
            data = request.get_json(force=True)

        # fix data if client is sloppy (http_async_client)
        if request.headers.get('User-Agent') == 'http_async_client':
            data = json.loads(list(data)[0])

        # sanity checks
        for k,v in data.items():
            if k not in VALID_REQUEST_DATA_ARGS.keys():
                raise http_exceptions.BadRequest("Request data argument '{}' not recognized".format(k))
            if not type(v) == VALID_REQUEST_DATA_ARGS[k]:
                raise http_exceptions.BadRequest("Request data argument '{}' not valid".format(k))
        if 'gwgroupid' not in data:
            raise http_exceptions.BadRequest('Gateway Group ID is required')
        elif 'type' not in data:
            raise http_exceptions.BadRequest('Notification Type is required')
        elif 'text_body' not in data:
            raise http_exceptions.BadRequest('Text Body is required')

        # lookup recipients
        gwgroupid = data.pop('gwgroupid')
        notif_type = data.pop('type')
        notification_row = db.query(dSIPNotification).filter(dSIPNotification.gwgroupid == gwgroupid).filter(dSIPNotification.type == notif_type).first()
        if notification_row is None:
            raise sql_exceptions.SQLAlchemyError('DB Entry Missing for {}'.format(str(gwgroupid)))

        # customize message based on type
        gwid = data.pop('gwid', None)
        gw_row = db.query(Gateways).filter(Gateways.gwid == gwid).first() if gwid is not None else None
        gw_name = strFieldsToDict(gw_row.description)['name'] if gw_row is not None else ''
        gwgroup_row = db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).first()
        gwgroup_name = strFieldsToDict(gwgroup_row.description)['name'] if gwgroup_row is not None else ''
        if notif_type == dSIPNotification.FLAGS.TYPE_OVERLIMIT.value:
            data['html_body'] = ('<html><head><style>.error{{border: 1px solid; margin: 10px 0px; padding: 15px 10px 15px 50px; background-color: #FF5555;}}</style></head>'
                                 '<body><div class="error"><strong>Call Limit Exceeded in Endpoint Group [{}] on Endpoint [{}]</strong></div></body>').format(gwgroup_name, gw_name)
        elif notif_type == dSIPNotification.FLAGS.TYPE_GWFAILURE.value:
            data['html_body'] = ('<html><head><style>.error{{border: 1px solid; margin: 10px 0px; padding: 15px 10px 15px 50px; background-color: #FF5555;}}</style></head>'
                                 '<body><div class="error"><strong>Failure Detected in Endpoint Group [{}] on Endpoint [{}]</strong></div></body>').format(gwgroup_name, gw_name)

        # # get attachments if any uploaded
        # data['attachments'] = []
        # if len(request.files) > 0:
        #     for upload in request.files:
        #         if upload.filename != '' and isValidFile(upload.filename):
        #             data['attachments'].append(upload)

        # TODO: we only support email at this time, add support for slack
        if notification_row.method == dSIPNotification.FLAGS.METHOD_EMAIL.value:
            data['recipients'] = [notification_row.value]
            sendEmail(**data)
        elif notification_row.method == dSIPNotification.FLAGS.METHOD_SLACK.value:
            pass

        payload['msg'] = 'Email Sent'
        return json.dumps(payload), status.HTTP_OK

    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        payload['error'] = "db"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(payload), status_code
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        payload['error'] = "http"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = ex.code or status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(payload), status_code
    except Exception as ex:
        debugException(ex, log_ex=True, print_ex=True, showstack=False)
        payload['error'] = "server"
        if len(str(ex)) > 0:
            payload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(payload), status_code


@api.route("/api/v1/endpointgroups/<int:gwgroupid>", methods=['DELETE'])
@api_security
def deleteEndpointGroup(gwgroupid):
    try:
        responsePayload = {}

        endpointgroup = db.query(GatewayGroups).filter(GatewayGroups.id==gwgroupid)
        if endpointgroup is not None:
            endpointgroup.delete(synchronize_session=False)
        else:
            responsePayload['status'] = "0"
            responsePayload['message'] = "The endpoint group doesn't exist"
            return json.dumps(responsePayload)


        calllimit = db.query(dSIPCallLimits).filter(dSIPCallLimits.gwgroupid==str(gwgroupid))
        if calllimit is not None:
            calllimit.delete(synchronize_session=False)

        subscriber =  db.query(Subscribers).filter(Subscribers.rpid==gwgroupid)
        if subscriber is not None:
            subscriber.delete(synchronize_session=False)

        typeFilter = "%gwgroup:{}%".format(gwgroupid)
        endpoints = db.query(Gateways).filter(Gateways.description.like(typeFilter))
        for endpoint in endpoints:
            endpoints.delete(synchronize_session=False)

        n = db.query(dSIPNotification).filter(dSIPNotification.gwgroupid == gwgroupid)
        for notification in n:
            n.delete(synchronize_session=False)

        cdrinfo = db.query(dSIPCDRInfo).filter(dSIPCDRInfo.gwgroupid == gwgroupid)
        if cdrinfo is not None:
            cdrinfo.delete(synchronize_session=False)

        domainmapping = db.query(dSIPMultiDomainMapping).filter(dSIPMultiDomainMapping.pbx_id == gwgroupid)
        if domainmapping is not None:
            domainmapping.delete(synchronize_session=False)

        db.commit()
        db.flush()

        responsePayload['status'] = 200

        return json.dumps(responsePayload)


    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))




@api.route("/api/v1/endpointgroups/<int:gwgroupid>", methods=['GET'])
@api_security
def getEndpointGroup(gwgroupid):
    try:
        responsePayload = {}
        strip = 0
        prefix = ""

        endpointgroup = db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).first()
        if endpointgroup is not None:
            responsePayload['name'] = strFieldsToDict(endpointgroup.description)['name']
        else:
            raise http_exceptions.NotFound("Endpoint Group Does Not Exist")

        # Send back the gateway groupid that was requested
        responsePayload['gwgroupid'] = gwgroupid

        calllimit = db.query(dSIPCallLimits).filter(dSIPCallLimits.gwgroupid == str(gwgroupid)).first()
        if calllimit is not None:
            responsePayload['calllimit'] = calllimit.limit

        # Check to see if a subscriber record exists.  If so, auth is userpwd
        auth = {}
        subscriber =  db.query(Subscribers).filter(Subscribers.rpid == gwgroupid).first()
        if subscriber is not None:
            auth['type'] = "userpwd"
            auth['user'] = subscriber.username
            auth['pass'] = subscriber.password
            auth['domain'] = subscriber.domain
        else:
            auth['type'] = "ip"

        responsePayload['auth'] = auth

        responsePayload['endpoints'] = []
        typeFilter = "%gwgroup:{}%".format(gwgroupid)

        endpointList = db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).first()
        if endpointList is not None:
            endpointGatewayList = endpointList.gwlist  
            endpointGatewayList = endpointGatewayList.split(',')
            endpoints = db.query(Gateways).filter(Gateways.gwid.in_(endpointGatewayList))
        
        for endpoint in endpoints:
            e ={}
            e['gwid'] = endpoint.gwid
            e['hostname'] = endpoint.address
            e['description'] = strFieldsToDict(endpoint.description)['name']
            e['maintmode'] = ""
            strip = endpoint.strip
            prefix = endpoint.pri_prefix

            responsePayload['endpoints'].append(e)

        responsePayload['strip'] = strip
        responsePayload['prefix'] = prefix

        # Notifications
        notifications = {}
        n = db.query(dSIPNotification).filter(dSIPNotification.gwgroupid == gwgroupid)
        for notification in n:
            #if notification.type == dSIPNotification.FLAGS.TYPE_MAXCALLLIMIT.value:
            if notification.type == 0:
                notifications['overmaxcalllimit'] = notification.value
            #if notification.type == dSIPNotification.FLAGS.TYPE_ENDPOINTFAILURE.value:
            if notification.type == 1:
                notifications['endpointfailure'] = notification.value

        responsePayload['notifications'] = notifications

        responsePayload['fusionpbx'] = {}
        domainmapping = db.query(dSIPMultiDomainMapping).filter(dSIPMultiDomainMapping.pbx_id == gwgroupid).first()
        if domainmapping is not None:
            responsePayload['fusionpbx']['enabled'] = "1"
            responsePayload['fusionpbx']['dbhost'] = domainmapping.db_host
            responsePayload['fusionpbx']['dbuser'] = domainmapping.db_username
            responsePayload['fusionpbx']['dbpass'] = domainmapping.db_password


        #CDR info
        responsePayload['cdr'] = {}
        cdrinfo = db.query(dSIPCDRInfo).filter(dSIPCDRInfo.gwgroupid == gwgroupid).first()
        if cdrinfo is not None:
            responsePayload['cdr']['cdr_email'] = cdrinfo.email
            responsePayload['cdr']['cdr_send_date'] = cdrinfo.send_date


        return json.dumps(responsePayload)

    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))





@api.route("/api/v1/endpointgroups", methods=['GET'])
@api_security
def listEndpointGroups():
    responsePayload = {}
    responsePayload['endpointgroups'] = []
    typeFilter = "%type:{}%".format(settings.FLT_PBX)
    try:
        checkDatabase()

        endpointgroups = db.query(GatewayGroups).filter(GatewayGroups.description.like(typeFilter)).all()
        for endpointgroup in endpointgroups:
            # Create a dictionary object
            eg = {}

            # Store the gateway group id
            eg['gwgroupid'] = endpointgroup.id


            # Grap the description field, which is comma seperated key/value pair
            fields = strFieldsToDict(endpointgroup.description)

            # Pull out the name value
            eg['name'] = fields['name']

            eg['gwlist'] = endpointgroup.gwlist

            # Push the responsePayload
            responsePayload['endpointgroups'].append(eg)

        return json.dumps(responsePayload)

    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))

@api.route("/api/v1/endpointgroups/<int:gwgroupid>", methods=['PUT'])
@api_security
def updateEndpointGroups(gwgroupid):

    try:
        if (settings.DEBUG):
            debugEndpoint()

        # Define a dictionary object that represents the payload
        responsePayload = {}

        # Set the status to 0, update it to 1 if the update is successful
        responsePayload['status'] = 0
        responsePayload['gwgroupid'] = None

        # Covert JSON message to Dictionary Object
        requestPayload = request.get_json()

        # Check parameters and raise exception if missing required parameters
        requiredParameters = ['name']

        try:
            for parameter in requiredParameters:
                if parameter not in requestPayload:
                    raise RequiredParameterMissing
                elif requestPayload[parameter] is None or len(requestPayload[parameter]) == 0:
                    raise RequiredParameterValueMissing
        except RequiredParameterMissing as ex:
                responsePayload['error'] = "{} attribute is missing".format(parameter)
                return json.dumps(responsePayload)
        except RequiredParameterValueMissing as ex:
                responsePayload['error'] = "The value of the {} attribute is missing".format(parameter)
                return json.dumps(responsePayload)

        # Update Gateway Name
        Gwgroup = db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).first()
        fields = strFieldsToDict(Gwgroup.description)
        fields['name'] = requestPayload['name']
        Gwgroup.description = dictToStrFields(fields)
        db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).update({'description': Gwgroup.description},synchronize_session=False)

        # Update Concurrent connections
        calllimit = requestPayload['calllimit'] if 'calllimit' in requestPayload else None
        if calllimit is not None and len(calllimit) > 0:
            if db.query(dSIPCallLimits).filter(dSIPCallLimits.gwgroupid == gwgroupid).update({'limit': calllimit},synchronize_session=False):
                db.flush()
                pass
            else:
                if isinstance(calllimit, str):
                    calllimit = int(calllimit)
                    if calllimit > -1:
                        CallLimit = dSIPCallLimits(gwgroupid,calllimit)
                        db.add(CallLimit)

        # Number of characters to strip and prefix
        strip = requestPayload['strip'] if 'strip' in requestPayload else ""
        if isinstance(strip,str):
            if len(strip) == 0:
                strip = None
        prefix = requestPayload['prefix'] if 'prefix' in requestPayload else None

        authtype = requestPayload['auth']['type'] if 'auth' in requestPayload and \
                                                     'type' in requestPayload['auth'] else ""

        # Update the AuthType userpwd settings
        if authtype == "userpwd":
            authuser = requestPayload['auth']['user'] if 'user' in requestPayload['auth'] else None
            authpass = requestPayload['auth']['pass'] if 'pass' in requestPayload['auth'] else None
            authdomain = requestPayload['auth']['domain'] if 'domain' in requestPayload['auth'] else settings.DOMAIN
            if authuser == None or authpass == None:
                raise AuthUsernameOrPasswordEmpty
            #Get the existing username and domain_name if it exists
            currentSubscriberInfo = db.query(Subscribers).filter(Subscribers.rpid == gwgroupid).first()
            if currentSubscriberInfo is not None:
                if authuser == currentSubscriberInfo.username and authpass == currentSubscriberInfo.password \
                and authdomain == currentSubscriberInfo.domain:
                    pass # The subscriber info is the same - no need to update
                else: #Check if the new username and domain is unique
                    if db.query(Subscribers).filter(Subscribers.username == authuser,Subscribers.domain == authdomain).scalar():
                        raise SubscriberUsernameTaken
                    else: # Update the Subscriber Info
                        currentSubscriberInfo.username=authuser
                        currentSubscriberInfo.password=authpass
                        currentSubscriberInfo.domain=authdomain
            else: #Create a new Suscriber entry
                   Subscriber = Subscribers(authuser, authpass, authdomain, gwgroupid)
                   db.add(Subscriber)
        #Delete the Subscriber info if IP is selected
        if authtype == "ip":
            subscriber =  db.query(Subscribers).filter(Subscribers.rpid==gwgroupid)
            if subscriber is not None:
                subscriber.delete(synchronize_session=False)


        #Update endpoints
        #Get List of existing endpoints
        #If endpoint sent over is not in the existing endpoint list then remove it
        typeFilter = "%gwgroup:{}%".format(gwgroupid)
        currentEndpoints = db.query(Gateways).filter(Gateways.description.like(typeFilter))

        IO.loginfo("****Before Endpoints****")
        if "endpoints" in requestPayload:
            gwlist=[]
            for endpoint in requestPayload['endpoints']:
                # gwid is really the gwid. If gwid is empty then this is a new endpoint
                if len(endpoint['gwid']) == 0:
                    hostname = endpoint['hostname'] if 'hostname' in endpoint else None
                    name = endpoint['description'] if 'description' in endpoint else None
                    if hostname is not None and name is not None \
                    and len(hostname) >0:
                        Gateway = Gateways(name, hostname, strip, prefix, settings.FLT_PBX,gwgroup=str(gwgroupid))
                        db.add(Gateway)
                        db.flush()
                        gwlist.append(str(Gateway.gwid))
                        if authtype == "ip":
                            Addr = Address(name, hostname,32, settings.FLT_PBX,gwgroup=str(gwgroupid))
                            db.add(Addr)
                        pass #Move to the next endpoint
                #Check if it exists in the currentEndpoints and update
                else:
                    for currentEndpoint in currentEndpoints:
                        IO.loginfo("endpoint pbx: {},currentEndpont: {},".format(endpoint['gwid'],currentEndpoint.gwid))
                        if int(endpoint['gwid']) == currentEndpoint.gwid:
                            IO.loginfo("Match:endpoint pbx: {},currentEndpont: {}".format(endpoint['gwid'],currentEndpoint.gwid))
                            fields['name'] = endpoint['description']
                            fields['gwgroup'] = gwgroupid
                            description = dictToStrFields(fields)
                            if db.query(Gateways).filter(Gateways.gwid == currentEndpoint.gwid).update({"address": endpoint['hostname'],"description":description }, synchronize_session=False):
                                IO.loginfo("adding gateway: {}".format(str(endpoint['gwid'])))
                                gwlist.append(str(endpoint['gwid']))
                                if authtype == "ip":
                                    db.query(Address).filter(and_(Address.ip_addr == currentEndpoint.address,Address.tag.like(typeFilter))).update(
                                            {"ip_addr":endpoint['hostname']},synchronize_session=False)

            db.commit()

            if len(gwlist) > 0:
                seperator = ","
                gwlistString = seperator.join(gwlist)
                IO.loginfo("gwlist: {}".format(gwlistString))
                # Remove any gateways that aren't on the list
                #db.query(Gateways).filter(and_(Gateways.gwid.notin_([gwlistString]),Gateways.description.like(typeFilter))).delete(synchronize_session=False)
                query = "DELETE FROM dr_gateways WHERE dr_gateways.gwid NOT IN ({}) AND dr_gateways.description LIKE '%gwgroup:{}%'".format(gwlistString,gwgroupid)
                db.execute(query)
                db.commit()


            if len(gwlist) == 0:
                db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).update( \
                    {"gwlist": ""}, synchronize_session=False)
                #Remove all gateways for that Endpoint group because the endpoint group is empty
                db.query(Gateways).filter(Gateways.description.like(typeFilter)).delete(synchronize_session=False)
            else:
                db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).update( \
                    {"gwlist": gwlistString}, synchronize_session=False)




        #Update notifications
        if 'notifications' in requestPayload:
            overmaxcalllimit = requestPayload['notifications']['overmaxcalllimit'] if 'overmaxcalllimit' in requestPayload['notifications'] else None
            endpointfailure = requestPayload['notifications']['endpointfailure'] if 'endpointfailure' in requestPayload['notifications'] else None

            if overmaxcalllimit is not None:
                # Try to update
                if db.query(dSIPNotification).filter(and_(dSIPNotification.gwgroupid==gwgroupid,dSIPNotification.type==0)).update({"value":overmaxcalllimit}):
                    pass
                else: # Add
                    type = 0
                    notification = dSIPNotification(gwgroupid, type, 0, overmaxcalllimit)
                    db.add(notification)
                #Remove
            else:
                db.query(dSIPNotification).filter(and_(dSIPNotification.gwgroupid==gwgroupid,dSIPNotification.type==0)).delete()


            if endpointfailure is not None:
                # Try to update
                if db.query(dSIPNotification).filter(and_(dSIPNotification.gwgroupid==gwgroupid,dSIPNotification.type==1)).update( \
                {"value":endpointfailure}):
                    pass
                else: # Add
                    type = 1
                    notification = dSIPNotification(gwgroupid, type, 0, endpointfailure)
                    db.add(notification)
                #Remove
            else:
                db.query(dSIPNotification).filter(and_(dSIPNotification.gwgroupid==gwgroupid,dSIPNotification.type==1)).delete()


        #Update CDR
        if 'cdr' in requestPayload:
            cdr_email = requestPayload['cdr']['cdr_email'] if 'cdr_email' in requestPayload['cdr'] else None
            cdr_send_date = requestPayload['cdr']['cdr_send_date'] if 'cdr_send_date' in requestPayload['cdr'] else None

            if len(cdr_email) > 0 and len(cdr_send_date) > 0:
                # Try to update

                if db.query(dSIPCDRInfo).filter(dSIPCDRInfo.gwgroupid==gwgroupid).update({"email":cdr_email,"send_date":cdr_send_date}):
                    pass
                else:
                    cdrinfo = dSIPCDRInfo(gwgroupid,cdr_email,cdr_send_date)
                    db.add(cdrinfo)
            else:
                # Removte CDR Info
                cdrinfo = db.query(dSIPCDRInfo).filter(dSIPCDRInfo.gwgroupid==gwgroupid).first()
                if cdrinfo is not None:
                    db.delete(cdrinfo)


        #Update FusionPBX
        if 'fusionpbx' in requestPayload:
            fusionpbxenabled = requestPayload['fusionpbx']['enabled'] if 'enabled' in requestPayload['fusionpbx'] else None
            fusionpbxdbhost = requestPayload['fusionpbx']['dbhost'] if 'dbhost' in requestPayload['fusionpbx'] else None
            fusionpbxdbuser = requestPayload['fusionpbx']['dbuser'] if 'dbuser' in requestPayload['fusionpbx'] else None
            fusionpbxdbpass = requestPayload['fusionpbx']['dbpass'] if 'dbpass' in requestPayload['fusionpbx'] else None

            # Convert fusionpbxenabled variable to int
            if isinstance(fusionpbxenabled,str):
                fusionpbxenabled = int(fusionpbxenabled)
            #Update
            if fusionpbxenabled == 1:
                #Update
                if db.query(dSIPMultiDomainMapping).filter(dSIPMultiDomainMapping.pbx_id==gwgroupid).update( \
                {"pbx_id":gwgroupid,"db_host":fusionpbxdbhost,"db_username":fusionpbxdbuser,"db_password":fusionpbxdbpass}):
                    pass
                else:
                    #Create new record
                    domainmapping = dSIPMultiDomainMapping(gwgroupid, fusionpbxdbhost, fusionpbxdbuser, \
                    fusionpbxdbpass, type=dSIPMultiDomainMapping.FLAGS.TYPE_FUSIONPBX.value)
                    db.add(domainmapping)
            #Delete
            elif fusionpbxenabled == 0:
                db.query(dSIPMultiDomainMapping).filter(dSIPMultiDomainMapping.pbx_id==gwgroupid).delete()


        db.commit()

        return jsonify(
            message='EndpointGroup Updated',
            gwgroupid=gwgroupid,
            status="200"
        )

    except Exception as ex:
        debugException(ex, log_ex=True, print_ex=True, showstack=False)
        # db.rollback()
        # db.flush()
        db.rollback()
        return jsonify(status=0, error=str(ex))




@api.route("/api/v1/endpointgroups", methods=['POST'])
@api_security
def addEndpointGroups():
    """
    Add Endpoint Group
    {
        name: <string>
        calllimit: <int>,
        auth: { type: "ip"|"userpwd",
                user: <string>
                pass: <string>
                domain: <string>
        },
        endpoints [
                    {hostname:<string>,description:<string>,maintmode:<bool>},
                    {hostname:<string>,description:<string>,maintmode:<bool>}
                  ],
        strip: <int>
        prefix: <string>
        notifications: {
            overmaxcalllimit: <string>,
            endpointfailure" <string>
        },
        cdr: {
            cdr_email: <string>,
            cdr_send_date: <string>
        }
        fusionpbx: {
            enabled: <bool>,
            dbhost: <string>,
            dbuser: <string>,
            dbpass: <string>
            }
    }
    """

    # Check parameters and raise exception if missing required parameters
    requiredParameters = ['name']

    # Define a dictionary object that represents the payload
    responsePayload = {}
    # Set the status to 0, update it to 1 if the update is successful
    responsePayload['status'] = 0
    responsePayload['gwgroupid'] = None

    try:
        if settings.DEBUG:
            debugEndpoint()

        # Convert JSON message to Dictionary Object
        requestPayload = request.get_json()

        for parameter in requiredParameters:
            if parameter not in requestPayload:
                raise http_exceptions.BadRequest("Request Argument '{}' is Required".format(parameter))
            elif requestPayload[parameter] is None or len(requestPayload[parameter]) == 0:
                raise http_exceptions.BadRequest("Value for Request Argument '{}' is Not Valid".format(parameter))

        # Process Gateway Name
        name = requestPayload['name']
        Gwgroup = GatewayGroups(name, type=settings.FLT_PBX)
        db.add(Gwgroup)
        db.flush()
        gwgroupid = Gwgroup.id
        responsePayload['gwgroupid'] = gwgroupid

        # Call limit
        # if calllimit is not None and isinstance(calllimit, int) and calllimit > 0:
        #     CallLimit = dSIPCallLimits(gwgroupid, calllimit)
        #     db.add(CallLimit)

        calllimit = requestPayload['calllimit'] if 'calllimit' in requestPayload else None
        if calllimit is not None and len(calllimit) > 0:
            calllimit = int(calllimit)
            if calllimit > -1:
                CallLimit = dSIPCallLimits(gwgroupid, calllimit)
                db.add(CallLimit)

        # Number of characters to strip and prefix
        strip = requestPayload['strip'] if 'strip' in requestPayload else ""
        if isinstance(strip,str) and len(strip) == 0:
            strip = None

        prefix = requestPayload['prefix'] if 'prefix' in requestPayload else None

        # Setup up authentication
        authtype = requestPayload['auth']['type'] if 'auth' in requestPayload and \
                                                     'type' in requestPayload['auth'] else ""

        if authtype == "userpwd":
            # Store Endpoint IP's in address tables
            authuser = requestPayload['auth']['user'] if 'user' in requestPayload['auth'] else None
            authpass = requestPayload['auth']['pass'] if 'pass' in requestPayload['auth'] else None
            authdomain = requestPayload['auth']['domain'] if 'domain' in requestPayload['auth'] else settings.DOMAIN

            if authuser == None or authpass == None:
                raise http_exceptions.BadRequest("Authentication Username and Password are Required")
            if db.query(Subscribers).filter(Subscribers.username == authuser, Subscribers.domain == authdomain).scalar():
                raise sql_exceptions.SQLAlchemyError('DB Entry Taken for Username {} in Domain {}'.format(authuser, authdomain))
            else:
                Subscriber = Subscribers(authuser, authpass, authdomain, gwgroupid)
                db.add(Subscriber)

        # Setup Endpoints
        if "endpoints" in requestPayload:
            #Store the gateway lists
            gwlist = []
            #Store Endpoint IP's in address tables
            for endpoint in requestPayload['endpoints']:
                hostname = endpoint['hostname'] if 'hostname' in endpoint else None
                name = endpoint['description'] if 'description' in endpoint else None

                if settings.DEBUG:
                    print("***{}***{}".format(hostname,name))

                if hostname is not None and name is not None and len(hostname) > 0:
                    Gateway = Gateways(name, hostname, strip, prefix, settings.FLT_PBX, gwgroup=str(gwgroupid))
                    db.add(Gateway)
                    db.flush()
                    gwlist.append(str(Gateway.gwid))
                if authtype == "ip":
                    Addr = Address(name, hostname, 32, settings.FLT_PBX, gwgroup=str(gwgroupid))
                    db.add(Addr)
            #Update the GatewayGroup with the lists of gateways
            seperator = ","
            gwlistString = seperator.join(gwlist)
            db.query(GatewayGroups).filter(GatewayGroups.id == gwgroupid).update(
                {'gwlist': gwlistString}, synchronize_session=False)




        # Setup notifications
        if 'notifications' in requestPayload:
            overmaxcalllimit = requestPayload['notifications']['overmaxcalllimit'] if 'overmaxcalllimit' in requestPayload['notifications'] else None
            endpointfailure = requestPayload['notifications']['endpointfailure'] if 'endpointfailure' in requestPayload['notifications'] else None

            if overmaxcalllimit is not None:
                type = dSIPNotification.FLAGS.TYPE_OVERLIMIT.value
                method = dSIPNotification.FLAGS.METHOD_EMAIL.value
                notification = dSIPNotification(gwgroupid, type, method, overmaxcalllimit)
                db.add(notification)

            if endpointfailure is not None:
                type = dSIPNotification.FLAGS.TYPE_GWFAILURE.value
                method = dSIPNotification.FLAGS.METHOD_EMAIL.value
                notification = dSIPNotification(gwgroupid, type, method, endpointfailure)
                db.add(notification)

        #Enable CDR
        if 'cdr' in requestPayload:
            cdr_email = requestPayload['cdr']['cdr_email'] if 'cdr_email' in requestPayload['cdr'] else None
            cdr_send_date = requestPayload['cdr']['cdr_send_date'] if 'cdr_send_date' in requestPayload['cdr'] else None

            if len(cdr_email) > 0 and len(cdr_send_date) > 0:
                cdrinfo = dSIPCDRInfo(gwgroupid,cdr_email,cdr_send_date)
                db.add(cdrinfo)

        # Enable FusionPBX
        if 'fusionpbx' in requestPayload:
            fusionpbxenabled = requestPayload['fusionpbx']['enabled'] if 'enabled' in requestPayload['fusionpbx'] else None
            fusionpbxdbhost = requestPayload['fusionpbx']['dbhost'] if 'dbhost' in requestPayload['fusionpbx'] else None
            fusionpbxdbuser = requestPayload['fusionpbx']['dbuser'] if 'dbuser' in requestPayload['fusionpbx'] else None
            fusionpbxdbpass = requestPayload['fusionpbx']['dbpass'] if 'dbpass' in requestPayload['fusionpbx'] else None

            # Convert fusionpbxenabled variable to int
            if isinstance(fusionpbxenabled, str):
                fusionpbxenabled = int(fusionpbxenabled)

            if fusionpbxenabled == 1:
                domainmapping = dSIPMultiDomainMapping(gwgroupid, fusionpbxdbhost, fusionpbxdbuser, fusionpbxdbpass,
                                                       type=dSIPMultiDomainMapping.FLAGS.TYPE_FUSIONPBX.value)
                db.add(domainmapping)

        # DEBUG
        # for key, value in data.items():
        #    print(key,value)
        #
        # send_email(recipients=recipients, text_body=text_body,data=None)

        db.commit()
        responsePayload['msg'] = 'EndpointGroup Created'
        responsePayload['status'] = 200
        return json.dumps(responsePayload), status.HTTP_OK


    except sql_exceptions.SQLAlchemyError as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        responsePayload['error'] = "db"
        if len(str(ex)) > 0:
            responsePayload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(responsePayload), status_code
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        responsePayload['error'] = "http"
        if len(str(ex)) > 0:
            responsePayload['msg'] = str(ex)
        status_code = ex.code or status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(responsePayload), status_code
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        responsePayload['error'] = "server"
        if len(str(ex)) > 0:
            responsePayload['msg'] = str(ex)
        status_code = status.HTTP_INTERNAL_SERVER_ERROR
        return json.dumps(responsePayload), status_code


def generateCDRS(gwgroupid, type=None, email=False, dtfilter=datetime.min):
    # Define a dictionary object that represents the payload
    responsePayload = {}

    try:

        query = "select * from dr_gw_lists where id = {}".format(gwgroupid)
        gwgroup = db.execute(query).first()
        if gwgroup is not None:
            gwlist = gwgroup.gwlist
            gwgroupName = strFieldsToDict(gwgroup.description)['name']
            if len(gwlist) == 0:
                responsePayload['status'] = "0"
                responsePayload['cdr'] = []
                responsePayload['recordCount'] = "0"
                responsePayload['message'] = "No endpoints are defined"
                return json.dumps(responsePayload)

        else:
            responsePayload['status'] = "0"
            responsePayload['message'] = "Endpont group doesn't exist"
            return json.dumps(responsePayload)

        query = """SELECT gwid, call_start_time, calltype AS direction, dst_username AS to_num, src_username AS from_num, src_ip, dst_domain, duration, sip_call_id
            FROM dr_gateways, cdrs WHERE (cdrs.src_ip = substring_index(dr_gateways.address,':',1) OR cdrs.dst_domain = substring_index(dr_gateways.address,':',1))
            AND gwid IN ({}) AND call_start_time >= '{}' ORDER BY call_start_time DESC;""".format(gwlist, dtfilter)

        cdrs = db.execute(query)
        rows = []
        for cdr in cdrs:
            row = {}
            row['gwid'] = cdr[0]
            row['call_start_time'] = str(cdr[1])
            row['calltype'] = cdr[2]

            if cdr[2] == "inbound":
                row['subscriber'] = cdr[3]
            else:
                row['subscriber'] = cdr[4]
            row['to_num'] = cdr[3]
            row['from_num'] = cdr[4]
            row['src_ip'] = cdr[5]
            row['dst_domain'] = cdr[6]
            row['duration'] = cdr[7]
            row['sip_call_id'] = cdr[8]
            row['gwgroupName'] = gwgroupName

            rows.append(row)


        responsePayload['status'] = "200"
        responsePayload['cdrs'] = rows
        responsePayload['recordCount'] = len(rows)


        if type == "csv":
            # Convert array to csv format
            lines = "ID,Call Start,Call Direction,Subscriber,To,From,Source,Destination Domain,Call Duration,Call ID,Endpoint Group\r"
            columns = ['gwid','call_start_time','calltype','subscriber','to_num','from_num','src_ip','dst_domain','duration','sip_call_id','gwgroupName']
            for row in rows:
                line = ""
                for column in columns:
                    line += str(row[column]) + ","
                # Remove the last comma and add end of line return
                line = line[:-1] + "\r"
                lines += line


            dateTime = time.strftime('%Y%m%d-%H%M%S')
            attachment = "attachment; filename={}_{}.csv".format(gwgroupName,dateTime)
            headers={"Content-disposition":attachment}

            if email:
                # recipients required
                cdr_info = db.query(dSIPCDRInfo).filter(dSIPCDRInfo.gwgroupid == gwgroupid).first()
                if cdr_info is not None:
                    # Write out csv to a file
                    filename = '/tmp/{}_{}.csv'.format(gwgroupName, dateTime)
                    f = open(filename, 'wb')
                    for line in lines:
                        f.write(line.encode())
                    f.close()

                    # Setup the parameters to send the email
                    data = {}
                    data['html_body'] = "<html>CDR Report for {}</html>".format(gwgroupName)
                    data['text_body'] = "CDR Report for {}".format(gwgroupName)
                    data['subject'] = "CDR Report for {}".format(gwgroupName)
                    data['attachments'] = []
                    data['attachments'].append(filename)
                    data['recipients'] = cdr_info.email.split(',')
                    sendEmail(**data)
                    # Remove CDR's from the payload thats being returned
                    responsePayload.pop('cdrs')
                    responsePayload['format'] = 'csv'
                    responsePayload['type'] = 'email'
                    return json.dumps(responsePayload)

            return Response(lines, mimetype="text/csv",headers=headers)
        else:
            return json.dumps(responsePayload)

    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))



@api.route("/api/v1/cdrs/endpointgroups/<int:gwgroupid>", methods=['GET'])
@api_security
def getGatewayGroupCDRS(gwgroupid=None, type=None, email=None):
    """
    Purpose

    Getting the cdrs for a gatewaygroup

    """
    if (settings.DEBUG):
        debugEndpoint()

    if type is None:
        type = "JSON"
    else:
        type = request.args.get('type')

    if email is None:
        email = False
    else:
        email = bool(request.args.get('email', 0))

    return generateCDRS(gwgroupid, type, email)


@api.route("/api/v1/cdrs/endpoint/<int:gwid>", methods=['GET'])
@api_security
def getGatewayCDRS(gwid=None):
    """
    Purpose

    Getting the cdrs for a gateway thats part of a gateway group

    """
    if (settings.DEBUG):
        debugEndpoint()

    # Define a dictionary object that represents the payload
    responsePayload = {}
    try:
        query = "select gwid, call_start_time, calltype as direction, dst_username as \
         number,src_ip, dst_domain, duration,sip_call_id \
         from dr_gateways,cdrs where cdrs.src_ip = dr_gateways.address and gwid={};".format(gwid)

        cdrs = db.execute(query)
        rows = []
        for cdr in cdrs:
            row = {}
            row['gwid'] = cdr[0]
            row['call_start_time'] = str(cdr[1])
            row['calltype'] = cdr[2]
            row['number'] = cdr[3]
            row['src_ip'] = cdr[4]
            row['dst_domain'] = cdr[5]
            row['duration'] = cdr[6]
            row['sip_call_id'] = cdr[7]

            rows.append(row)

        if rows is not None:
            responsePayload['status'] = "200"
            responsePayload['cdrs'] = rows
            responsePayload['recordCount'] = len(rows)
        else:
            responsePayload['status'] = "200"
            responsePayload['cdrs'] = rows
            responsePayload['recordCount'] = len(rows)

        return json.dumps(responsePayload)

    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))

@api.route("/api/v1/backupandrestore/backup", methods=['GET'])
@api_security
def createBackup(gwid=None):
    """
    Purpose

    Generate a backup of the database

    """
    if (settings.DEBUG):
        debugEndpoint()

    # Define a dictionary object that represents the payload
    responsePayload = {}
    try:

        backup_name = time.strftime('%Y%m%d-%H%M%S') + ".sql"
        backup_path = os.path.join(settings.BACKUP_FOLDER, backup_name)
#        dumpcmd = "mysqldump --single-transaction --opt --events --routines --triggers --host='" + settings.KAM_DB_HOST + \
#                  "' --user='" + settings.KAM_DB_USER + "' --password='" + settings.KAM_DB_PASS + "' " + settings.KAM_DB_NAME + \
#                  """ | sed -r -e 's|DEFINER=[`"'"'"']\w*[`"'"'"']@[`"'"'"']\w*[`"'"'"']||g'""" + " > " + backup_path
#        os.system(dumpcmd)

        dumpcmd = ['/usr/bin/mysqldump', '--single-transaction', '--opt', '--routines', '--triggers', '--hex-blob', '-h', settings.KAM_DB_HOST, '-u',
                   settings.KAM_DB_USER, '-p{}'.format(settings.KAM_DB_PASS), '-B', settings.KAM_DB_NAME]
        with open(backup_path, 'wb') as fp:
            dump = subprocess.Popen(dumpcmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).communicate()[0]
            dump = re.sub(rb'''DEFINER=[`"\'][a-zA-Z0-9_%]*[`"\']@[`"\'][a-zA-Z0-9_%]*[`"\']''', b'', dump, flags=re.MULTILINE)
            dump = re.sub(rb'ENGINE=MyISAM', b'ENGINE=InnoDB', dump, flags=re.MULTILINE)
            fp.write(dump)

        #lines = "It wrote the backup"
        #attachment = "attachment; filename=dsiprouter_{}_{}.sql".format(settings.VERSION,backupDateTime)
        #headers={"Content-disposition":attachment}
        #return Response(lines, mimetype="text/plain",headers=headers)
        return send_file(backup_path, attachment_filename=backup_name, as_attachment=True)
        
    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))

@api.route("/api/v1/backupandrestore/restore", methods=['POST'])
@api_security
def restoreBackup():
    """
    Purpose

    Restore backup of the database

    """
    if (settings.DEBUG):
        debugEndpoint()

    content_type = str.lower(request.headers.get('Content-Type'))
    if 'multipart/form-data' in content_type:
         data = request.form.to_dict(flat=True)
    elif 'application/x-www-form-urlencoded' in content_type:
        data = request.form.to_dict(flat=True)
    else:
        data = request.get_json(force=True)

    KAM_DB_USER = settings.KAM_DB_USER
    KAM_DB_PASS = settings.KAM_DB_PASS

    if 'db_username' in data.keys():
        KAM_DB_USER = str(data.get('db_username'))
        if KAM_DB_USER !='':
            KAM_DB_PASS = str(data.get('db_password'))

    # fix data if client is sloppy (http_async_client)
    if request.headers.get('User-Agent') == 'http_async_client':
        data = json.loads(list(data)[0])

    # Define a dictionary object that represents the payload
    responsePayload = {}
    try:

        if 'file' not in request.files:
            responsePayload['status'] = "401"
            responsePayload['error'] = "No file was sent"
            return responsePayload

        file = request.files['file']

        if file.filename=='':
            responsePayload['status'] = "401"
            responsePayload['error'] = "No file name was sent"
            return responsePayload
        
        if file and allowed_file(file.filename, ALLOWED_EXTENSIONS={'sql'}):
            filename = secure_filename(file.filename)
            restore_path = os.path.join(settings.BACKUP_FOLDER, filename)
            file.save(restore_path)
            responsePayload['status'] = "200"
            responsePayload['error'] = "The backup file was uploaded"
        else:
            responsePayload['status'] = "400"
            responsePayload['error'] = "Improper file upload"
            return responsePayload

#        if len(KAM_DB_PASS) == 0:
#            restorecmd = "mysql --host='" + settings.KAM_DB_HOST + "' --user='" + str(KAM_DB_USER) + "' " + settings.KAM_DB_NAME + " < " + restore_path
#        else:
#            restorecmd = "mysql --host='" + settings.KAM_DB_HOST + "' --user='" + str(KAM_DB_USER) + "' --password='" + str(KAM_DB_PASS) + "' " + settings.KAM_DB_NAME + " < " + restore_path        
#        os.system(restorecmd)

        if len(KAM_DB_PASS) == 0:
            restorecmd = ['/usr/bin/mysql', '-h', settings.KAM_DB_HOST, '-u', KAM_DB_USER, '-D', settings.KAM_DB_NAME]
        else:
            restorecmd = ['/usr/bin/mysql', '-h', settings.KAM_DB_HOST, '-u', KAM_DB_USER, '-p{}'.format(KAM_DB_PASS), '-D', settings.KAM_DB_NAME]

        with open(restore_path, 'rb') as fp:
            subprocess.Popen(restorecmd, stdin=fp, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).communicate()
        
        responsePayload['status'] = "200"
        responsePayload['error'] = "The restore was successful"
        
        return responsePayload

    except http_exceptions.HTTPException as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "http"
        db.rollback()
        db.flush()
        return jsonify(status=0,error=str(ex))
    except Exception as ex:
        debugException(ex, log_ex=False, print_ex=True, showstack=False)
        error = "server"
        return jsonify(status=0,error=str(ex))

# Generates a password with a length of 32 charactors
@api.route("/api/v1/sys/generatepassword", methods=['GET'])
@api_security
def generatePassword():
    chars ="abcdefghijklmnopqrstvwxyz0123456789"
    password=''
    for c in range(32):
        password += random.choice(chars)
    return jsonify(password=password)
