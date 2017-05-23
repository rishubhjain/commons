# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
#
#     (1) Redistributions of source code must retain the above copyright
#     notice, this list of conditions and the following disclaimer.
#
#     (2) Redistributions in binary form must reproduce the above copyright
#     notice, this list of conditions and the following disclaimer in
#     the documentation and/or other materials provided with the
#     distribution.
#
#     (3)The name of the author may not be used to
#     endorse or promote products derived from this software without
#     specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE AUTHOR ``AS IS'' AND ANY EXPRESS OR
# IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY DIRECT,
# INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
# HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT,
# STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING
# IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
"""
All fields.
"""

import json


class Field(object):
    """Base class for all Tendrl central store fields.

    """

    def __init__(self, name, value=None):
        """Initializes a new Field instance.

        :param name: The name of the field
        :type name: str
        """
        self.name = name
        self._value = value

    @property
    def json(self):
        """Returns a json version of the field.

        :returns: JSON representation.
        :rtype: str
        """
        return json.dumps({self.name: self._value})

    @property
    def value(self):
        """Returns the value of the field.

        :returns: The value of the field
        :rtype: mixed
        """
        return self._value

    @value.setter
    def value(self, value):
        """Sets the field value.

        :param value: The value to use.
        :type value: mixed
        """
        self._set_value(value)

    def _set_value(self, value):
        """Internal method that sets the field value.

        :param value: The value to use.
        :type value: mixed
        """
        self._value = value

    def render(self):
        """Renders the field into a structure that can be persisted to etcd.

        :returns: A structure to be used with etcd
        :rtype: dict
        """
        return {
            'name': self.name,
            'key': self.name,
            'value': self._value,
            'dir': False,
        }


class _CastField(Field):  # pragma: no cover
    """Base class for all Fields which force specific types.

    """
    _caster = None

    def _set_value(self, value):
        """Internal method that sets the field value.

        :param value: The value to use.
        :type value: mixed
        """
        self._value = self._caster(value)


class IntField(_CastField):
    """A Field that forces a cast to an int.

    """
    _caster = int


class StrField(_CastField):
    """A Field that forces a cast to a str.

    """
    _caster = str


class DateTimeField(Field):
    """A Field that forces a cast to a datetime.datetime instance.

    """

    def __init__(self, name, value):
        """Initializes an instance of datetime.datetime UTC/isoformat.

        :param name: The name of the field
        :type name: str
        """
        super(DateTimeField, self).__init__(name)
        self._value = value

    @property
    def json(self):
        """Returns a json version of the field.

        :returns: JSON representation.
        :rtype: str
        """
        return json.dumps({
            self.name: str(self._value.isoformat()),
        })

    def render(self):
        """Renders the field into a structure that can be persisted to etcd.

        :returns: A structure to be used with etcd
        :rtype: dict
        """
        return {
            'name': self.name,
            'key': self.name,
            'value': str(self._value.isoformat()),
            'dir': False,
        }


class ListField(Field):
    """A list Field that forces a cast to json.dumps(list).

    """

    def __init__(self, name, value):
        """Initializes an instance of list.

        :param name: The name of the field
        :type name: str
        """
        super(ListField, self).__init__(name)
        self._value = value
        if self._value:
            self._value = list(set(self._value))

    @property
    def json(self):
        """Returns a json version of the field.

        :returns: JSON representation.
        :rtype: str
        """
        return json.dumps({
            self.name: json.dumps(self._value),
        })

    def render(self):
        """Renders the field into a structure that can be persisted to etcd.

        :returns: A structure to be used with etcd
        :rtype: dict
        """
        return {
            'name': self.name,
            'key': self.name,
            'value': self._value,
            'dir': False,
        }


class DictField(Field):
    """A Field that only accepts dicts.

    """

    def __init__(self, name, value, caster=None):
        """Initializes an instance of DictField.

        :param caster: A caster structure for casting dictionary items.
        :type caster: dict
        """
        super(DictField, self).__init__(name)
        self._caster = caster or {'str': 'str'}
        self._value = value

    @property
    def json(self):
        """Returns a json version of the field.

        .. note::

           DictField serializes the dictionary without the name.

        :returns: JSON representation.
        :rtype: str
        """
        return json.dumps(self._value)

    def _set_value(self, value):
        """Internal method that sets the field value.

        :param value: The value to use.
        :type value: dict
        :raises: TypeError
        """
        if type(value) != dict:
            raise TypeError('Must use dict. Provided: {0}'.format(type(value)))

        # Force casting if we were given a caster.
        if self._caster:
            for x in value.keys():
                caster = self._caster.get(x, None)
                if callable(caster):
                    value[x] = caster(value[x])

        super(DictField, self)._set_value(value)

    def render(self):
        """Renders the field into a structure that can be persisted to etcd.

        :returns: A list of structures to be used with etcd
        :rtype: list
        """
        rendered = []
        for x in self._value.keys():
            rendered.append({
                'name': self.name,
                'key': '{0}/{1}'.format(self.name, x),
                'value': self._value[x],
                'dir': True,
            })
        return rendered
