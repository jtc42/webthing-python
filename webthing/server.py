"""Python Web Thing server implementation."""

import asyncio
import json
import logging
import socket
import sys
import types
import typing

import tornado.concurrent
import tornado.gen
import tornado.httpserver
import tornado.ioloop
import tornado.web
import tornado.websocket
from tornado.iostream import StreamClosedError
from zeroconf import ServiceInfo, Zeroconf

from .errors import PropertyError
from .json import JSONEncoder
from .subscriber import Subscriber
from .utils import get_addresses, get_ip


class BaseHandler(tornado.web.RequestHandler):
    """Base handler that is initialized with a thing."""

    def initialize(self, thing, hosts, json_encoder):
        """
        Initialize the handler.

        thing -- Thing managed by this server
        hosts -- list of allowed hostnames
        """
        self.thing = thing
        self.hosts = hosts
        self.json_encoder = json_encoder

    def prepare(self):
        """Validate Host header."""
        host = self.request.headers.get("Host", None)
        if host is not None and host.lower() in self.hosts:
            return

        raise tornado.web.HTTPError(403)

    def set_default_headers(self, *args, **kwargs):
        """Set the default headers for all requests."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header(
            "Access-Control-Allow-Headers",
            "Origin, X-Requested-With, Content-Type, Accept",
        )
        self.set_header("Access-Control-Allow-Methods", "GET, HEAD, PUT, POST, DELETE")

    def options(self, *args, **kwargs):
        """Handle an OPTIONS request."""
        self.set_status(204)

    async def write_and_flush(self, data):
        # Write data to memory
        self.write(data)
        # Write data to network
        await self.flush()

    async def represent_response(
        self, data, content_type: str = "application/json", headers: dict = None
    ):
        headers = headers or {}
        for k, v in headers:
            self.set_header(k, v)

        self.set_header("Content-Type", content_type)

        # If the response data is a generator, handle it specially
        if isinstance(data, (typing.AsyncGenerator, types.GeneratorType)):
            self.set_header(
                "Cache-Control",
                "no-store, no-cache, must-revalidate, pre-check=0, post-check=0, max-age=0",
            )
            self.set_header("Pragma", "no-cache")

            if isinstance(data, typing.AsyncGenerator):
                async for frame in data:
                    # Write data to network
                    try:
                        await self.write_and_flush(frame)
                    except StreamClosedError:
                        logging.warning("Stream is closed")
                        break
            elif isinstance(data, types.GeneratorType):
                for frame in data:
                    # Write data to network
                    try:
                        await self.write_and_flush(frame)
                    except StreamClosedError:
                        logging.warning("Stream is closed")
                        break
        # If the response data is not a generator
        else:
            # If the response contentType is JSON, format data first
            if content_type == "application/json":
                data = json.dumps(data, cls=self.json_encoder)
            # Write data
            self.write(data)


class ThingHandler(tornado.websocket.WebSocketHandler, Subscriber):
    """Handle a request to /."""

    def initialize(self, thing, hosts, json_encoder):
        """
        Initialize the handler.

        thing -- Thing managed by this server
        hosts -- list of allowed hostnames
        """
        self.thing = thing
        self.hosts = hosts
        self.json_encoder = json_encoder

    def prepare(self):
        """Validate Host header."""
        host = self.request.headers.get("Host", None)
        if host is not None and host in self.hosts:
            return

        raise tornado.web.HTTPError(403)

    def set_default_headers(self, *args, **kwargs):
        """Set the default headers for all requests."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header(
            "Access-Control-Allow-Headers",
            "Origin, X-Requested-With, Content-Type, Accept",
        )
        self.set_header("Access-Control-Allow-Methods", "GET, HEAD, PUT, POST, DELETE")

    def options(self, *args, **kwargs):
        """Handle an OPTIONS request."""
        self.set_status(204)

    @tornado.gen.coroutine
    def get(self):
        """
        Handle a GET request, including websocket requests.
        """
        if self.thing is None:
            self.set_status(404)
            self.finish()
            return

        if self.request.headers.get("Upgrade", "").lower() == "websocket":
            yield tornado.websocket.WebSocketHandler.get(self)
            return

        self.set_header("Content-Type", "application/json")
        ws_href = "{}://{}".format(
            "wss" if self.request.protocol == "https" else "ws",
            self.request.headers.get("Host", ""),
        )

        description = self.thing.as_thing_description()
        description["links"].append(
            {
                "rel": "alternate",
                "href": "{}{}".format(ws_href, self.thing.get_href()),
            }
        )
        description["base"] = "{}://{}{}".format(
            self.request.protocol,
            self.request.headers.get("Host", ""),
            self.thing.get_href(),
        )
        description["securityDefinitions"] = {
            "nosec_sc": {
                "scheme": "nosec",
            },
        }
        description["security"] = "nosec_sc"

        self.write(json.dumps(description, cls=self.json_encoder))
        self.finish()

    def open(self):
        """Handle a new connection."""
        self.thing.add_subscriber(self)

    def on_message(self, message):
        """
        Handle an incoming message.

        message -- message to handle
        """
        try:
            message = json.loads(message)
        except ValueError:
            try:
                self.write_message(
                    json.dumps(
                        {
                            "messageType": "error",
                            "data": {
                                "status": "400 Bad Request",
                                "message": "Parsing request failed",
                            },
                        },
                        cls=self.json_encoder,
                    )
                )
            except tornado.websocket.WebSocketClosedError:
                pass

            return

        if "messageType" not in message or "data" not in message:
            try:
                self.write_message(
                    json.dumps(
                        {
                            "messageType": "error",
                            "data": {
                                "status": "400 Bad Request",
                                "message": "Invalid message",
                            },
                        },
                        cls=self.json_encoder,
                    )
                )
            except tornado.websocket.WebSocketClosedError:
                pass

            return

        msg_type = message["messageType"]
        if msg_type == "setProperty":
            for property_name, property_value in message["data"].items():
                try:
                    self.thing.set_property(property_name, property_value)
                except PropertyError as e:
                    self.write_message(
                        json.dumps(
                            {
                                "messageType": "error",
                                "data": {
                                    "status": "400 Bad Request",
                                    "message": str(e),
                                },
                            },
                            cls=self.json_encoder,
                        )
                    )
        elif msg_type == "requestAction":
            for action_name, action_params in message["data"].items():
                input_ = None
                if "input" in action_params:
                    input_ = action_params["input"]

                action = self.thing.init_action(action_name, input_)
                if action:
                    tornado.ioloop.IOLoop.current().spawn_callback(action.start)
                else:
                    self.write_message(
                        json.dumps(
                            {
                                "messageType": "error",
                                "data": {
                                    "status": "400 Bad Request",
                                    "message": "Invalid action request",
                                    "request": message,
                                },
                            },
                            cls=self.json_encoder,
                        )
                    )
        elif msg_type == "addEventSubscription":
            for event_name in message["data"].keys():
                self.thing.add_event_subscriber(event_name, self)
        else:
            try:
                self.write_message(
                    json.dumps(
                        {
                            "messageType": "error",
                            "data": {
                                "status": "400 Bad Request",
                                "message": "Unknown messageType: " + msg_type,
                                "request": message,
                            },
                        },
                        cls=self.json_encoder,
                    )
                )
            except tornado.websocket.WebSocketClosedError:
                pass

    def on_close(self):
        """Handle a close event on the socket."""
        self.thing.remove_subscriber(self)

    def check_origin(self, origin):
        """Allow connections from all origins."""
        return True

    def update_property(self, property_):
        """
        Send an update about a Property.

        :param property_: Property
        """
        message = json.dumps(
            {
                "messageType": "propertyStatus",
                "data": {
                    property_.name: property_.get_value(),
                },
            },
            cls=self.json_encoder,
        )

        self.write_message(message)

    def update_action(self, action):
        """
        Send an update about an Action.

        :param action: Action
        """
        message = json.dumps(
            {
                "messageType": "actionStatus",
                "data": action.as_action_description(),
            },
            cls=self.json_encoder,
        )

        self.write_message(message)

    def update_event(self, event):
        """
        Send an update about an Event.

        :param event: Event
        """
        message = json.dumps(
            {
                "messageType": "event",
                "data": event.as_event_description(),
            },
            cls=self.json_encoder,
        )

        self.write_message(message)


class PropertiesHandler(BaseHandler):
    """Handle a request to /properties."""

    async def get(self):
        """
        Handle a GET request.
        """
        if self.thing is None:
            self.set_status(404)
            return

        await self.represent_response(
            await self.thing.get_properties(), "application/json"
        )


class PropertyHandler(BaseHandler):
    """Handle a request to /properties/<property>."""

    async def get(self, property_name=None):
        """
        Handle a GET request.

        property_name -- the name of the property from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        prop = self.thing.find_property(property_name)
        if prop:
            data = await self.thing.get_property(property_name)
            await self.represent_response(data, prop.get_content_type())
        else:
            self.set_status(404)

    async def put(self, property_name=None):
        """
        Handle a PUT request.

        property_name -- the name of the property from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        try:
            args = json.loads(self.request.body.decode())
        except ValueError:
            self.set_status(400)
            return

        prop = self.thing.find_property(property_name)
        if prop:
            try:
                await self.thing.set_property(property_name, args)
            except PropertyError:
                self.set_status(400)
                return
            await self.represent_response(
                await self.thing.get_property(property_name), prop.get_content_type()
            )
        else:
            self.set_status(404)


class ActionsHandler(BaseHandler):
    """Handle a request to /actions."""

    async def get(self):
        """
        Handle a GET request.
        """
        if self.thing is None:
            self.set_status(404)
            return

        await self.represent_response(self.thing.get_action_object_descriptions())

    async def post(self):
        """
        Handle a POST request.
        """
        if self.thing is None:
            self.set_status(404)
            return

        try:
            args = json.loads(self.request.body.decode())
        except ValueError:
            self.set_status(400)
            return

        keys = list(message.keys())
        if len(keys) != 1:
            self.set_status(400)
            return

        action_name = keys[0]
        action_params = message[action_name]
        input_ = None
        if "input" in action_params:
            input_ = action_params["input"]

        action = self.thing.init_action(action_name, input_)
        if action:
            response = action.as_action_description()

            # Start the action
            tornado.ioloop.IOLoop.current().spawn_callback(action.start)

            self.set_status(201)
            await self.represent_response(response)
        else:
            self.set_status(400)


class ActionHandler(BaseHandler):
    """Handle a request to /actions/<action_name>."""

    async def get(self, action_name=None):
        """
        Handle a GET request.

        action_name -- name of the action from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        await self.represent_response(
            self.thing.get_action_object_descriptions(action_name=action_name)
        )

    async def post(self, action_name=None):
        """
        Handle a POST request.
        """
        if self.thing is None:
            self.set_status(404)
            return

        try:
            args = json.loads(self.request.body.decode())
        except ValueError:
            self.set_status(400)
            return

        action = self.thing.init_action(action_name, args)
        if action:
            response = action.as_action_description()

            # Start the action
            tornado.ioloop.IOLoop.current().spawn_callback(action.start)

            self.set_status(201)
            await self.represent_response(response)
        else:
            self.set_status(400)


class ActionIDHandler(BaseHandler):
    """Handle a request to /actions/<action_name>/<action_id>."""

    async def get(self, action_name=None, action_id=None):
        """
        Handle a GET request.

        action_name -- name of the action from the URL path
        action_id -- the action ID from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        action = self.thing.get_action(action_name, action_id)
        if action is None:
            self.set_status(404)
            return

        await self.represent_response(action.as_action_description())

    def delete(self, action_name=None, action_id=None):
        """
        Handle a DELETE request.

        action_name -- name of the action from the URL path
        action_id -- the action ID from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        if self.thing.remove_action(action_name, action_id):
            self.set_status(204)
        else:
            self.set_status(404)


class EventsHandler(BaseHandler):
    """Handle a request to /events."""

    async def get(self):
        """
        Handle a GET request.
        """
        if self.thing is None:
            self.set_status(404)
            return

        await self.represent_response(self.thing.get_event_descriptions())


class EventHandler(BaseHandler):
    """Handle a request to /events/<event_name>."""

    async def get(self, event_name=None):
        """
        Handle a GET request.

        event_name -- name of the event from the URL path
        """
        if self.thing is None:
            self.set_status(404)
            return

        await self.represent_response(
            self.thing.get_event_descriptions(event_name=event_name)
        )


class WebThingServer:
    """Server to represent a Web Thing over HTTP."""

    def __init__(
        self,
        thing,
        port=80,
        hostname=None,
        ssl_options=None,
        additional_routes=None,
        base_path="",
        debug=False,
        json_encoder=JSONEncoder,
    ):
        """
        Initialize the WebThingServer.

        For documentation on the additional route format, see:
        https://www.tornadoweb.org/en/stable/web.html#tornado.web.Application

        thing -- thing managed by this server -- should be of type Thing
        port -- port to listen on (defaults to 80)
        hostname -- Optional host name, i.e. mything.com
        ssl_options -- dict of SSL options to pass to the tornado server
        additional_routes -- list of additional routes to add to the server
        base_path -- base URL path to use, rather than '/'
        """
        self.thing = thing
        self.name = thing.title
        self.port = port
        self.hostname = hostname
        self.base_path = base_path.rstrip("/")

        self.json_encoder = json_encoder

        system_hostname = socket.gethostname().lower()
        self.hosts = [
            "localhost",
            "localhost:{}".format(self.port),
            "{}.local".format(system_hostname),
            "{}.local:{}".format(system_hostname, self.port),
        ]

        for address in get_addresses():
            self.hosts.extend(
                [
                    address,
                    "{}:{}".format(address, self.port),
                ]
            )

        if self.hostname is not None:
            self.hostname = self.hostname.lower()
            self.hosts.extend(
                [
                    self.hostname,
                    "{}:{}".format(self.hostname, self.port),
                ]
            )

        self.thing.set_href_prefix(self.base_path)
        handlers = [
            [
                r"/?",
                ThingHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/properties/?",
                PropertiesHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/properties/(?P<property_name>[^/]+)/?",
                PropertyHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/actions/?",
                ActionsHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/actions/(?P<action_name>[^/]+)/?",
                ActionHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/actions/(?P<action_name>[^/]+)/(?P<action_id>[^/]+)/?",
                ActionIDHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/events/?",
                EventsHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
            [
                r"/events/(?P<event_name>[^/]+)/?",
                EventHandler,
                dict(
                    thing=self.thing, hosts=self.hosts, json_encoder=self.json_encoder
                ),
            ],
        ]

        if isinstance(additional_routes, list):
            handlers = additional_routes + handlers

        if self.base_path:
            for h in handlers:
                h[0] = self.base_path + h[0]

        self.app = tornado.web.Application(handlers, debug=debug)
        self.app.is_tls = ssl_options is not None
        self.server = tornado.httpserver.HTTPServer(self.app, ssl_options=ssl_options)

    def start(self):
        """Start listening for incoming connections."""
        args = [
            "_webthing._tcp.local.",
            "{}._webthing._tcp.local.".format(self.name),
        ]
        kwargs = {
            "port": self.port,
            "properties": {
                "path": "/",
            },
            "server": "{}.local.".format(socket.gethostname()),
        }

        if self.app.is_tls:
            kwargs["properties"]["tls"] = "1"

        if sys.version_info.major == 3:
            kwargs["addresses"] = [socket.inet_aton(get_ip())]
        else:
            kwargs["address"] = socket.inet_aton(get_ip())

        self.service_info = ServiceInfo(*args, **kwargs)
        self.zeroconf = Zeroconf()
        self.zeroconf.register_service(self.service_info)

        self.server.listen(self.port)
        tornado.ioloop.IOLoop.current().start()

    def stop(self):
        """Stop listening."""
        self.zeroconf.unregister_service(self.service_info)
        self.zeroconf.close()
        self.server.stop()
