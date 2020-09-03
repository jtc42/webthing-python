from __future__ import division

import asyncio
import logging
import time
import uuid

from webthing import Action, Event, Property, Thing, Value, WebThingServer


class OverheatedEvent(Event):
    def __init__(self, thing, data):
        Event.__init__(self, thing, "overheated", data=data)


def make_thing():
    thing = Thing(
        "urn:dev:ops:my-lamp-1234",
        "My Lamp",
        ["OnOffSwitch", "Light"],
        "A web connected lamp",
    )

    thing.add_context("https://iot.mozilla.org/schemas")

    on_property = Property(
        thing,
        "on",
        Value(True, None, lambda x: print(x)),
        metadata={
            "@type": "OnOffProperty",
            "title": "On/Off",
            "type": "boolean",
            "description": "Whether the lamp is turned on",
        },
    )

    brightness_property = Property(
        thing,
        "brightness",
        Value(50, None, lambda x: print(x)),
        metadata={
            "@type": "BrightnessProperty",
            "title": "Brightness",
            "type": "integer",
            "description": "The level of light from 0-100",
            "minimum": 0,
            "maximum": 100,
            "unit": "percent",
        },
    )

    thing.add_property(on_property)
    thing.add_property(brightness_property)

    async def fade_function(args):
        print("Starting fade function")
        await asyncio.sleep(args["duration"] / 1000)
        await brightness_property.set_value(args["brightness"])
        print("Finished fade function")
        return "Return value"

    fade_action = Action(
        thing,
        "fade",
        fade_function,
        metadata={
            "title": "Fade",
            "description": "Fade the lamp to a given level",
        },
        input_={
            "type": "object",
            "required": [
                "brightness",
                "duration",
            ],
            "properties": {
                "brightness": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 100,
                    "unit": "percent",
                },
                "duration": {
                    "type": "integer",
                    "minimum": 1,
                    "unit": "milliseconds",
                },
            },
        },
        output={"type": "string"},
    )

    thing.add_action(fade_action)

    thing.add_available_event(
        "overheated",
        {
            "description": "The lamp has exceeded its safe operating temperature",
            "type": "number",
            "unit": "degree celsius",
        },
    )

    return thing


def run_server():
    thing = make_thing()

    server = WebThingServer(thing, port=8888, debug=True)
    try:
        logging.info("starting the server")
        server.start()
    except KeyboardInterrupt:
        logging.info("stopping the server")
        server.stop()
        logging.info("done")


if __name__ == "__main__":
    logging.basicConfig(
        level=10, format="%(asctime)s %(filename)s:%(lineno)s %(levelname)s %(message)s"
    )
    run_server()
