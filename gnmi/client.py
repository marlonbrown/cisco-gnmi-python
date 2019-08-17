"""Copyright 2019 Cisco Systems All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

 * Redistributions of source code must retain the above copyright
 notice, this list of conditions and the following disclaimer.

The contents of this file are licensed under the Apache License, Version 2.0
(the "License"); you may not use this file except in compliance with the
License. You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
License for the specific language governing permissions and limitations under
the License.
"""

"""Python gNMI wrapper to ease usage."""

import logging
import json

try:
    # Python 3
    from urllib.parse import urlparse
except ImportError:
    # Python 2
    from urlparse import urlparse

import grpc
from . import proto


class Client(object):
    """gNMI gRPC wrapper client to ease usage of gNMI.

    Returns relatively raw response data. Response data may be accessed according
    to the gNMI specification.

    Attributes
    ----------
    username : str
    password : str
    timeout : uint
    tls_enabled : bool

    Methods
    -------
    get(...)
        Get a snapshot of config, state, operational, or all forms of data.
    set(...)
        Update, replace, or delete configuration.
    
    Examples
    --------
    >>> from gnmi import Client
    >>> client = Client('127.0.0.1:57400', 'demo', 'demo')
    >>> get_response = client.get_xpaths('interfaces/interface')
    ...
    """

    """Defining property due to gRPC timeout being based on a C long type.
    Should really define this based on architecture.
    32-bit C long max value. "Infinity".
    """
    __C_MAX_LONG = 2147483647

    def __init__(
        self,
        target,
        username,
        password,
        timeout=__C_MAX_LONG,
        credentials=None,
        credentials_from_file=False,
        tls_server_override=None,
        tls_enabled=True,
    ):
        """Initializes the gNMI gRPC client stub and defines auxiliary attributes.

        Parameters
        ----------
        target : str
            The host[:port] to issue gNMI requests against.
        username : str
        password : str
        timeout : uint, optional
            Timeout for request which sets a deadline for return.
            Defaults to "infinity"
        credentials : str, optional
            PEM contents or PEM file path.
        credentials_from_file : bool, optional
            Indicates that credentials is a file path.
        tls_server_override : str, optional
            TLS server name if PEM will not match.
            Please only utilize in testing.
        tls_enabled : bool, optional
            Whether or not to utilize a secure channel.
            If disabled, and functional, gNMI server is against specification.
        """
        self.username = username
        self.password = password
        self.timeout = int(timeout)
        self.tls_enabled = tls_enabled
        self.__target = self.__gen_target(target)
        self.__credentials = self.__gen_credentials(credentials, credentials_from_file)
        self.__options = self.__gen_options(tls_server_override)
        self.__client = self.__gen_client(
            self.__target, self.__credentials, self.__options, self.tls_enabled
        )

    def __repr__(self):
        """JSON dump a dict of basic attributes."""
        return json.dumps(
            {
                "target": self.__target,
                "tls_enabled": self.tls_enabled,
                "is_secure": bool(self.__credentials),
                "username": self.username,
                "password": self.password,
                "timeout": self.timeout,
            }
        )

    def __gen_metadata(self):
        """Generates expected gRPC call metadata."""
        return [("username", self.username), ("password", self.password)]

    def capabilities(self):
        """Capabilities allows the client to retrieve the set of capabilities that
        is supported by the target. This allows the target to validate the
        service version that is implemented and retrieve the set of models that
        the target supports. The models can then be specified in subsequent RPCs
        to restrict the set of data that is utilized.
        Reference: gNMI Specification Section 3.2

        Returns
        -------
        proto.gnmi_pb2.CapabilityResponse
        """
        message = proto.gnmi_pb2.CapabilityRequest()
        response = self.__client.Capabilities(message, metadata=self.__gen_metadata())
        return response

    def get(
        self,
        paths,
        paths_prefix=None,
        data_type=proto.gnmi_pb2.GetRequest.DataType.ALL,
        encoding=proto.gnmi_pb2.Encoding.JSON_IETF,
        use_models=None,
        extension=None,
    ):
        """A snapshot of the requested data that exists on the target.

        Parameters
        ----------
        paths : iterable of proto.gnmi_pb2.Path
            An iterable of Paths to request data of.
        prefix : proto.gnmi_pb2.Path, optional
            A path to prefix all Paths in paths
        data_type : proto.gnmi_pb2.GetRequest.DataType, optional
            A member of the GetRequest.DataType enum to specify what datastore to target
            [ALL, CONFIG, STATE, OPERATIONAL]
        encoding : proto.gnmi_pb2.Encoding, optional
            A member of the proto.gnmi_pb2.Encoding enum specifying desired encoding of returned data
            [JSON, BYTES, PROTO, ASCII, JSON_IETF]
        use_models : iterable of proto.gnmi_pb2.ModelData, optional
        extension : iterable of proto.gnmi_ext.Extension, optional

        Returns
        -------
        proto.gnmi_pb2.GetResponse
        """
        data_type = self.__check_proto_enum(
            "data_type",
            data_type,
            "GetRequest.DataType",
            proto.gnmi_pb2.GetRequest.DataType,
        )
        encoding = self.__check_proto_enum(
            "encoding", encoding, "Encoding", proto.gnmi_pb2.Encoding
        )
        request = proto.gnmi_pb2.GetRequest()
        if not isinstance(paths, (list, set)):
            raise Exception("paths must be an iterable containing Path(s)!")
        map(request.path.append, paths)
        request.type = data_type
        request.encoding = encoding
        if prefix:
            request.prefix = prefix
        if use_models:
            request.use_models = use_models
        if extension:
            request.extension = extension
        get_response = self.__client.Get(request, metadata=self.__gen_metadata())
        return get_response

    def get_xpaths(self, xpaths, data_type="ALL", encoding="JSON_IETF"):
        """A convenience wrapper for get() which forms proto.gnmi_pb2.Path from supplied xpaths.

        Parameters
        ----------
        xpaths : iterable of str or str
            An iterable of XPath strings to request data of
            If simply a str, wraps as a list for convenience
        data_type : proto.gnmi_pb2.GetRequest.DataType, optional
            A direct value or key from the GetRequest.DataType enum
        encoding : proto.gnmi_pb2.GetRequest.Encoding, optional
            A direct value or key from the Encoding enum

        Returns
        -------
        get()
        """
        gnmi_path = None
        if isinstance(xpaths, (list, set)):
            gnmi_path = map(self.__parse_xpath_to_gnmi_path, set(xpaths))
        elif isinstance(xpaths, str):
            gnmi_path = [self.__parse_xpath_to_gnmi_path(xpaths)]
        else:
            raise Exception(
                "xpaths must be a single xpath string or iterable of xpath strings!"
            )
        return self.get(gnmi_path, data_type=data_type, encoding=encoding)

    def set(
        self, prefix=None, updates=None, replaces=None, deletes=None, extensions=None
    ):
        """Modifications to the configuration of the target.

        Parameters
        ----------
        prefix : proto.gnmi_pb2.Path, optional
            The Path to prefix all other Paths defined within other messages
        update : iterable of proto.gnmi_pb2.Update, optional
            The Updates to update configuration with.
        replace : proto.gnmi_pb2.Update, optional
            The Updates which replaces other configuration.
            The main difference between replace and update is replace will remove non-referenced nodes.
        delete : proto.gnmi_pb2.Update, optional
            The Updates which refers to elements for deletion.
        extensions : iterable of proto.gnmi_ext.Extension, optional

        Returns
        -------
        proto.gnmi_pb2.SetResponse
        """
        request = proto.gnmi_pb2.SetRequest()
        if prefix:
            request.prefix = prefix
        for item in [updates, replaces, deletes]:
            if not item:
                continue
            if not isinstance(item, (list, set)):
                raise Exception("updates, replaces, and deletes must be iterables!")
        if updates:
            map(request.update.append, updates)
        if replaces:
            map(request.replace.append, replaces)
        if deletes:
            map(request.delete.append, deletes)
        if extensions:
            map(request.extension.append, extensions)
        response = self.__client.Set(request, metadata=self.__gen_metadata())
        return response

    def set_json(
        self,
        update_json_configs=None,
        replace_json_configs=None,
        delete_json_configs=None,
        ietf=True,
    ):
        """A convenience wrapper for set() which assumes JSON payloads and constructs desired messages.
        All parameters are optional, but at least one must be present.

        Parameters
        ----------
        update_json_configs : iterable of JSON configurations, optional
            JSON configs to apply as updates.
        replace_json_configs : iterable of JSON configurations, optional
            JSON configs to apply as replacements.
        delete_json_configs : iterable of JSON configurations, optional
            JSON configs to apply as deletions.
        ietf : bool, optional
            Use JSON_IETF vs JSON.
        
        Returns
        -------
        set()
        """
        if not any([update_json_configs, replace_json_configs, delete_json_configs]):
            raise Exception("Must supply at least one set of configurations to method!")

        def check_configs(name, configs):
            if isinstance(name, str):
                logging.debug("Handling %s as JSON string.", name)
                try:
                    json.loads(name)
                except:
                    raise Exception("{name} is invalid JSON!".format(name=name))
                configs = [configs]
            elif isinstance(name, dict):
                logging.debug("Handling %s as already serialized JSON object.", name)
                configs = [json.dumps(configs)]
            elif not isinstance(configs, (list, set)):
                raise Exception(
                    "{name} must be an iterable of config strings!".format(name=name)
                )
            return configs

        def create_updates(name, configs):
            if not configs:
                return
            configs = check_configs(name, configs)
            updates = []
            for config in configs:
                update = proto.gnmi_pb2.Update()
                if ietf:
                    update.val = proto.gnmi_pb2.TypedValue(json_ietf_val=config)
                else:
                    update.val = proto.gnmi_pb2.TypedValue(json_val=config)
                updates.append(update)
            return updates

        updates = create_updates("update_json_configs", update_json_configs)
        replaces = create_updates("replace_json_configs", replace_json_configs)
        deletes = create_updates("delete_json_configs", delete_json_configs)
        return self.set(updates=updates, replaces=replaces, deletes=deletes)

    @staticmethod
    def __gen_target(target, netloc_prefix="//", default_port=50051):
        """Parses and validates a supplied target URL for gRPC calls.
        Uses urllib to parse the netloc property from the URL.
        netloc property is, effectively, fqdn/hostname:port.
        This provides some level of URL validation and flexibility.
        Returns netloc property of target.
        """
        if netloc_prefix not in target:
            target = netloc_prefix + target
        parsed_target = urlparse(target)
        if not parsed_target.netloc:
            raise ValueError("Unable to parse netloc from target URL %s!" % target)
        if parsed_target.scheme:
            logging.debug("Scheme identified in target, ignoring and using netloc.")
        target_netloc = parsed_target.netloc
        if parsed_target.port is None:
            ported_target = "%s:%i" % (parsed_target.hostname, default_port)
            logging.debug("No target port detected, reassembled to %s.", ported_target)
            target_netloc = Client.__gen_target(ported_target)
        return target_netloc

    @staticmethod
    def __gen_client(target, credentials=None, options=None, tls_enabled=True):
        """Instantiates and returns the gNMI gRPC client stub over
        an insecure or secure channel.
        """
        client = None
        if not tls_enabled:
            logging.warning(
                "TLS MUST be enabled per gNMI specification. If your gNMI implementation works without TLS, it is non-compliant."
            )
            insecure_channel = grpc.insecure_channel(target)
            client = proto.gnmi_pb2_grpc.gNMIStub(insecure_channel)
        else:
            channel_creds = grpc.ssl_channel_credentials(credentials)
            secure_channel = grpc.secure_channel(target, channel_creds, options)
            client = proto.gnmi_pb2_grpc.gNMIStub(secure_channel)
        return client

    @staticmethod
    def __gen_credentials(credentials, credentials_from_file):
        """Generate credentials either by reading credentials from
        the specified file or return the original creds specified.
        """
        if not credentials:
            return None
        if credentials_from_file:
            with open(credentials, "rb") as creds_fd:
                credentials = creds_fd.read()
        return credentials

    @staticmethod
    def __gen_options(tls_server_override):
        """Generate options tuple for gRPC overrides, etc.
        Only TLS server is handled currently.
        """
        options = []
        if tls_server_override:
            options.append(("grpc.ssl_target_name_override", tls_server_override))
        return tuple(options)

    @staticmethod
    def __parse_xpath_to_gnmi_path(xpath):
        if not isinstance(xpath, str):
            raise Exception("xpath must be a string!")
        path = proto.gnmi_pb2.Path()
        for element in xpath.split("/"):
            path.elem.append(proto.gnmi_pb2.PathElem(name=element))
        return path

    @staticmethod
    def __validate_enum_arg(name, valid_options, message=None):
        """Construct error around enumeration validation."""
        if name not in valid_options:
            if not message:
                message = "%s must be one of %s" % (name, ", ".join(valid_options))
            raise ValueError(message)

    @staticmethod
    def __check_proto_enum(value_name, value, enum_name, enum):
        enum_value = None
        if value not in enum.keys() and value not in enum.values():
            raise Exception(
                "{name}={value} not in {enum_name} enum! Please try any of {options}.".format(
                    name=value_name,
                    value=str(value),
                    enum_name=enum_name,
                    options=str(enum.keys()),
                )
            )
        if value in enum.keys():
            enum_value = enum.Value(value)
        else:
            enum_value = value
        return enum_value
