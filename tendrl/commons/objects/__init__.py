import etcd

import abc
import copy
import hashlib
import json
import six
import sys
import types

from tendrl.commons.event import Event
from tendrl.commons.message import ExceptionMessage
from tendrl.commons.message import Message
from tendrl.commons.utils.central_store import utils as cs_utils
from tendrl.commons.utils import etcd_utils
from tendrl.commons.utils import time_utils


@six.add_metaclass(abc.ABCMeta)
class BaseObject(object):
    def __init__(self, *args, **kwargs):
        # Tendrl internal objects should populate their own self._defs
        if not hasattr(self, "internal"):
            self._defs = BaseObject.load_definition(self)
        if hasattr(self, "internal"):
            if not hasattr(self, "_defs"):
                raise Exception("Internal Object must provide its own "
                                "definition via '_defs' attr")

    def load_definition(self):
        try:
            Event(
                Message(
                    priority="debug",
                    publisher=NS.publisher_id,
                    payload={"message": "Load definitions (.yml) for "
                                        "namespace.%s.objects.%s" %
                                        (self._ns.ns_name,
                                         self.__class__.__name__)
                             }
                )
            )
        except KeyError:
            sys.stdout.write("Load definitions (.yml) for namespace.%s.objects"
                             ".%s" % (self._ns.ns_name,
                                      self.__class__.__name__))
        try:
            return self._ns.get_obj_definition(self.__class__.__name__)
        except KeyError as ex:
            msg = "Could not find definitions (.yml) for " \
                  "namespace.%s.objects.%s" %\
                  (self._ns.ns_name, self.__class__.__name__)
            try:
                Event(
                    ExceptionMessage(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": "error",
                                 "exception": ex}
                    )
                )
            except KeyError:
                sys.stdout.write(str(ex))
            try:
                Event(
                    Message(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": msg}
                    )
                )
            except KeyError:
                sys.stdout.write(msg)
            raise Exception(msg)

    def save(self, update=True, ttl=None):
        self.render()
        if "Message" not in self.__class__.__name__:
            try:
                # Generate current in memory object hash
                self.hash = self._hash()
                _hash_key = "/{0}/hash".format(self.value)
                _stored_hash = None
                try:
                    _stored_hash = NS._int.client.read(_hash_key).value
                except (etcd.EtcdConnectionFailed, etcd.EtcdException) as ex:
                    if type(ex) != etcd.EtcdKeyNotFound:
                        NS._int.reconnect()
                        _stored_hash = NS._int.client.read(_hash_key).value
                if self.hash == _stored_hash:
                    # No changes in stored object and current object,
                    # dont save current object to central store
                    if ttl:
                        etcd_utils.refresh(self.value, ttl)
                    return
            except TypeError:
                # no hash for this object, save the current hash as is
                pass

        if update:
            current_obj = self.load()
            for attr, val in vars(self).iteritems():
                if isinstance(val, (types.FunctionType,
                                    types.BuiltinFunctionType,
                                    types.MethodType, types.BuiltinMethodType,
                                    types.UnboundMethodType)) or \
                        attr.startswith("_") or attr in ['value', 'list']:
                    continue

                if val is None and hasattr(current_obj, attr):
                    # if self.attr is None, use attr value from central
                    # store (i.e. current_obj.attr)
                    if getattr(current_obj, attr):
                        setattr(self, attr, getattr(current_obj, attr))

        self.updated_at = str(time_utils.now())
        for item in self.render():
            '''
                Note: Log messages in this file have try-except
                blocks to run
                in the condition when the node_agent has not been
                started and
                name spaces are being created.
            '''
            try:
                Event(
                    Message(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": "Writing %s to %s" %
                                            (item['key'], item['value'])
                                 }
                    )
                )
            except KeyError:
                sys.stdout.write("Writing %s to %s" % (item['key'],
                                                       item['value']))
            # convert list, dict (json) to python based on definitions
            _type = self._defs.get("attrs", {}).get(item['name'],
                                                    {}).get("type")
            if _type:
                if _type.lower() in ['json', 'list']:
                    if item['value']:
                        try:
                            item['value'] = json.dumps(item['value'])
                        except ValueError as ex:
                            _msg = "Error save() attr %s for object %s" % \
                                   (item['name'], self.__name__)
                            Event(
                                ExceptionMessage(
                                    priority="debug",
                                    publisher=NS.publisher_id,
                                    payload={"message": _msg,
                                             "exception": ex
                                             }
                                )
                            )
            try:
                NS._int.wclient.write(item['key'], item['value'], quorum=True)
            except (etcd.EtcdConnectionFailed, etcd.EtcdException):
                NS._int.wreconnect()
                NS._int.wclient.write(item['key'], item['value'], quorum=True)
        if ttl:
            etcd_utils.refresh(self.value, ttl)

    def load_all(self):
        value = '/'.join(self.value.split('/')[:-1])
        try:
            etcd_resp = NS._int.client.read(value)
        except (etcd.EtcdConnectionFailed, etcd.EtcdException) as ex:
                    if type(ex) != etcd.EtcdKeyNotFound:
                        NS._int.reconnect()
                        etcd_resp = NS._int.client.read(value)
                    else:
                        return None
        ins = []
        for item in etcd_resp.leaves:
            self.value = item.key
            ins.append(self.load())
        return ins

    def load(self):
        if "Message" not in self.__class__.__name__:
            try:
                # Generate current in memory object hash
                self.hash = self._hash()
                _hash_key = "/{0}/hash".format(self.value)
                _stored_hash = None
                try:
                    _stored_hash = NS._int.client.read(_hash_key).value
                except (etcd.EtcdConnectionFailed, etcd.EtcdException) as ex:
                    if type(ex) != etcd.EtcdKeyNotFound:
                        NS._int.reconnect()
                        _stored_hash = NS._int.client.read(_hash_key).value
                if self.hash == _stored_hash:
                    # No changes in stored object and current object,
                    # dont save current object to central store
                    return self
            except TypeError:
                # no hash for this object, save the current hash as is
                pass

        _copy = self._copy_vars()

        for item in _copy.render():
            try:
                Event(
                    Message(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": "Reading %s" % item['key']}
                    )
                )
            except KeyError:
                sys.stdout.write("Reading %s" % item['key'])

            try:
                etcd_resp = NS._int.client.read(item['key'], quorum=True)
            except (etcd.EtcdConnectionFailed, etcd.EtcdException) as ex:
                if type(ex) == etcd.EtcdKeyNotFound:
                    continue
                else:
                    NS._int.reconnect()
                    etcd_resp = NS._int.client.read(item['key'], quorum=True)

            value = etcd_resp.value
            if item['dir']:
                key = item['key'].split('/')[-1]
                dct = dict(key=value)
                if hasattr(_copy, item['name']):
                    dct = getattr(_copy, item['name'])
                    if type(dct) == dict:
                        dct[key] = value
                    else:
                        setattr(_copy, item['name'], dct)
                else:
                    setattr(_copy, item['name'], dct)
                continue

            # convert list, dict (json) to python based on definitions
            _type = self._defs.get("attrs", {}).get(item['name'],
                                                    {}).get("type")
            if _type:
                if _type.lower() in ['json', 'list']:
                    if value:
                        try:
                            value = json.loads(value.decode('utf-8'))
                        except ValueError as ex:
                            _msg = "Error load() attr %s for object %s" % \
                                   (item['name'], self.__name__)
                            Event(
                                ExceptionMessage(
                                    priority="debug",
                                    publisher=NS.publisher_id,
                                    payload={"message": _msg,
                                             "exception": ex
                                             }
                                )
                            )
                    else:
                        if _type.lower() == "list":
                            value = list()
                        if _type.lower() == "json":
                            value = dict()

            setattr(_copy, item['name'], value)
        return _copy

    def exists(self):
        self.render()
        _exists = False
        try:
            NS._int.client.read("/{0}".format(self.value))
            _exists = True
        except (etcd.EtcdConnectionFailed, etcd.EtcdException) as ex:
            if type(ex) != etcd.EtcdKeyNotFound:
                NS._int.reconnect()
                NS._int.client.read("/{0}".format(self.value))
                _exists = True
        return _exists

    def _map_vars_to_tendrl_fields(self):
        _fields = {}
        for attr, value in vars(self).iteritems():
            _type = self._defs.get("attrs", {}).get(attr,
                                                    {}).get("type")
            if _type:
                _type = _type.lower()

            if value is None:
                value = ""
            if attr.startswith("_") or attr in ['value', 'list']:
                continue
            _fields[attr] = cs_utils.to_tendrl_field(attr, value, _type)

        return _fields

    def render(self):
        """Renders the instance into a structure for central store based on

        its key (self.value)

        :returns: The structure to use for setting.
        :rtype: list(dict{key=str,value=any})
        """

        rendered = []
        _fields = self._map_vars_to_tendrl_fields()
        if _fields:
            for name, field in _fields.iteritems():
                items = field.render()
                if type(items) != list:
                    items = [items]
                for i in items:
                    i['key'] = '/{0}/{1}'.format(self.value, i['key'])
                    rendered.append(i)
        return rendered

    @property
    def json(self):
        """Dumps the entire object as a json structure.

        """
        data = {}
        _fields = self._map_vars_to_tendrl_fields()
        if _fields:
            for name, field in _fields.iteritems():
                data[field.name] = json.loads(field.json)
                # Flatten if needed
                if field.name in data[field.name].keys():
                    data[field.name] = data[field.name][field.name]

        return json.dumps(data)

    def _hash(self):
        self.hash = None
        self.updated_at = None

        # Above items cant be part of hash
        _obj_str = "".join(sorted(self.json))
        return hashlib.md5(_obj_str).hexdigest()

    def _copy_vars(self):
        # Creates a copy intance of $obj using it public vars
        _public_vars = {}
        for attr, value in vars(self).iteritems():
            if attr.startswith("_") or attr in ['hash', 'updated_at',
                                                'value', 'list']:
                continue
            if type(value) in [dict, list]:
                value = copy.deepcopy(value)
            _public_vars[attr] = value
        return self.__class__(**_public_vars)


@six.add_metaclass(abc.ABCMeta)
class BaseAtom(object):
    def __init__(self, parameters=None):
        self.parameters = parameters or dict()

        # Tendrl internal atoms should populate their own self._defs
        if not hasattr(self, "internal"):
            self._defs = BaseAtom.load_definition(self)
        if hasattr(self, "internal"):
            if not hasattr(self, "_defs"):
                raise Exception("Internal Atom must provide its own "
                                "definition via '_defs' attr")

    def load_definition(self):
        try:
            Event(
                Message(
                    priority="debug",
                    publisher=NS.publisher_id,
                    payload={"message": "Load definitions (.yml) for "
                                        "namespace.%s."
                                        "objects.%s.atoms.%s" %
                                        (self._ns.ns_name, self.obj.__name__,
                                         self.__class__.__name__)
                             }
                )
            )
        except KeyError:
            sys.stdout.write("Load definitions (.yml) for "
                             "namespace.%s.objects.%s."
                             "atoms.%s" % (self._ns.ns_name, self.obj.__name__,
                                           self.__class__.__name__))
        try:
            return self._ns.get_atom_definition(self.obj.__name__,
                                                self.__class__.__name__)
        except KeyError as ex:
            msg = "Could not find definitions (.yml) for" \
                  "namespace.%s.objects.%s.atoms.%s" % (self._ns.ns_src,
                                                        self.obj.__name__,
                                                        self.__class__.__name__
                                                        )
            try:
                Event(
                    ExceptionMessage(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": "Error", "exception": ex}
                    )
                )
            except KeyError:
                sys.stderr.write("Error: %s" % ex)
            try:
                Event(
                    Message(
                        priority="debug",
                        publisher=NS.publisher_id,
                        payload={"message": msg}
                    )
                )
            except KeyError:
                sys.stderr.write(msg)
            raise Exception(msg)

    @abc.abstractmethod
    def run(self):
        raise AtomNotImplementedError(
            'define the function run to use this class'
        )


class AtomNotImplementedError(NotImplementedError):
    def __init__(self, err):
        self.message = "run function not implemented. {}".format(err)
        super(AtomNotImplementedError, self).__init__(self.message)


class AtomExecutionFailedError(Exception):
    def __init__(self, err):
        self.message = "Atom Execution failed. Error:" + \
                       " {}".format(err)
        super(AtomExecutionFailedError, self).__init__(self.message)
