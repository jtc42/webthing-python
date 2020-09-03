from __future__ import division

import asyncio
import io
import logging
import sys
from datetime import datetime

from PIL import Image, ImageDraw

from webthing import Property, Thing, Value, WebThingServer

if (
    sys.version_info[0] == 3
    and sys.version_info[1] >= 8
    and sys.platform.startswith("win")
):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

"""
PIL spams the logger with debug-level information. This is a pain when debugging api.app.
We override the logging settings in api.app by setting a level for PIL here.
"""
pil_logger = logging.getLogger("PIL")
pil_logger.setLevel(logging.INFO)


class StreamGenerator:
    def __init__(self):
        self.stream = io.BytesIO()
        self.running = False
        self.event = asyncio.Event()

    def _start_runner(self):
        print("Starting frame runner")
        task = asyncio.create_task(self.frame_loop())
        self.running = True
        return task

    def generate_new_dummy_image(self):
        # Create a dummy image to serve in the stream
        image = Image.new("RGB", (640, 480), color=(0, 0, 0),)

        draw = ImageDraw.Draw(image)
        draw.text(
            (20, 70),
            "Current time: {}".format(datetime.now().strftime("%d/%m/%Y, %H:%M:%S")),
        )

        image.save(self.stream, format="JPEG")

    async def frame_loop(self):
        while True:
            await asyncio.sleep(1)  # Only serve frames at 1fps
            self.event.clear()
            # Reset stream
            self.stream.seek(0)
            self.stream.truncate()

            # Generate new dumm image
            self.generate_new_dummy_image()
            self.event.set()

    async def stream_generator(self):
        if not self.running:
            self._start_runner()

        served_image_timestamp = time.time()
        my_boundary = "--boundarydonotcross\n"
        while True:
            interval = 1.0
            if served_image_timestamp + interval < time.time():
                # Wait for current frame to finish being generated
                await self.event.wait()
                # Get the current frame
                img = self.stream.getvalue()
                # Add frame header data
                served_image_timestamp = time.time()
                prefix = (
                    my_boundary
                    + "Content-type: image/jpeg\r\n"
                    + "Content-length: %s\r\n\r\n" % len(img)
                )
                yield prefix.encode() + img
            else:
                # Delay by interval before checking for next frame
                await asyncio.sleep(interval)

    async def snapshot(self):
        if not self.running:
            self._start_runner()
        await self.event.wait()
        return self.stream.getvalue()


def make_thing():
    stream_generator = StreamGenerator()

    thing = Thing(
        "urn:dev:ops:my-lamp-1234",
        "My Lamp",
        ["OnOffSwitch", "Light"],
        "A web connected lamp",
    )

    thing.add_property(
        Property(
            thing,
            "snapshot",
            Value(None, stream_generator.snapshot, None),
            metadata={"title": "Snapshot", "readOnly": True},
            content_type="image/jpeg",
        )
    )

    thing.add_property(
        Property(
            thing,
            "stream",
            Value(None, stream_generator.stream_generator, None),
            metadata={"title": "Stream", "readOnly": True},
            content_type="multipart/x-mixed-replace;boundary=--boundarydonotcross",
        )
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
