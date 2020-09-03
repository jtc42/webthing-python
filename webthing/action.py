"""High-level Action base class implementation."""

from copy import deepcopy
import uuid
import asyncio
from .utils import timestamp


class ActionObject:
    """An ActionObject represents an individual action on a thing."""

    def __init__(self, thing, name, target, input_):
        """
        Initialize the object.

        id_ ID of this action
        thing -- the Thing this action belongs to
        name -- name of the action
        input_ -- any action inputs
        """
        self._task = None

        self.id = uuid.uuid4().hex
        self.thing = thing
        self.name = name

        self.target_function = target
        self.input = input_
        self.output = None

        self.href_prefix = ""
        self.href = "/actions/{}/{}".format(self.name, self.id)
        self.status = "created"
        self.time_requested = timestamp()
        self.time_completed = None

    def as_action_description(self):
        """
        Get the action description.

        Returns a dictionary describing the action.
        """
        description = {
            "name": self.name,
            "id": self.id,
            "href": self.href_prefix + self.href,
            "timeRequested": self.time_requested,
            "timeCompleted": self.time_completed,
            "status": self.status,
        }

        if self.input is not None:
            description["input"] = self.input

        if self.output is not None:
            description["output"] = self.output

        return description

    def set_href_prefix(self, prefix):
        """
        Set the prefix of any hrefs associated with this action.

        prefix -- the prefix
        """
        self.href_prefix = prefix

    def get_id(self):
        """Get this action's ID."""
        return self.id

    def get_name(self):
        """Get this action's name."""
        return self.name

    def get_href(self):
        """Get this action's href."""
        return self.href_prefix + self.href

    def get_status(self):
        """Get this action's status."""
        return self.status

    def get_thing(self):
        """Get the thing associated with this action."""
        return self.thing

    def get_time_requested(self):
        """Get the time the action was requested."""
        return self.time_requested

    def get_time_completed(self):
        """Get the time the action was completed."""
        return self.time_completed

    def get_input(self):
        """Get the inputs for this action."""
        return self.input

    async def start(self):
        """Start performing the action."""
        self.status = "pending"
        self.thing.action_notify(self)
        # If the action function is async
        if asyncio.iscoroutinefunction(self.target_function):
            self._task = asyncio.ensure_future(self.target_function(self.input))
        # If the action function is not async
        else:
            # Run in the default ThreadPoolExecutor
            self._task = asyncio.get_event_loop().run_in_executor(
                None, self.target_function, self.input
            )
        self._task.add_done_callback(self.finish)

    def cancel(self):
        if self._task:
            self._task.cancel()

    def finish(self, future):
        """Finish performing the action."""
        try:
            self.output = future.result()
            self.status = "completed"
        except asyncio.CancelledError:
            self.status = "cancelled"
        except Exception as e:
            self.output = str(e)
            self.status = "error"
        self.time_completed = timestamp()
        self.thing.action_notify(self)


class Action:
    """An Action represents a class of actions on a thing."""

    def __init__(self, thing, name, invokeaction=None, metadata=None, input_=None, output=None):
        self.thing = thing
        self.name = name
        self.href_prefix = ""
        self.href = "/actions/{}".format(self.name)

        self.metadata = metadata if metadata is not None else {}
        self.input = input_ if input_ is not None else {}
        self.output = output if output is not None else {}

        self.invokeaction_forwarder = invokeaction or (lambda: None)

        self.queue = []

    def as_action_description(self):
        """
        Get the action description.

        Returns a dictionary describing the action.
        """
        description = deepcopy(self.metadata)

        # Create WoT TD v1 input and output keys
        if "input" not in description:
            description["input"] = self.input

        if "output" not in description:
            description["output"] = {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "id": {"type": "string"},
                    "href": {"type": "string", "format": "uri"},
                    "timeRequested": {"type": "string", "format": "date-time"},
                    "timeCompleted": {"type": "string", "format": "date-time"},
                    "status": {"type": "string", "enum": ["created", "pending", "completed", "cancelled", "error"]},
                    **({"output": self.output} if self.output else {}),
                    **({"input": self.input} if self.input else {}),
                }
            }

        # Create forms
        if "forms" not in description:
            description["forms"] = []

        description["forms"].append(
            {
                "op": "invokeaction",
                "href": self.href_prefix + self.href,
                "htv:methodName": "POST",
            }
        )

        return description

    def invokeaction(self, input_):
        action_obj = ActionObject(
            self.thing, self.name, self.invokeaction_forwarder, input_
        )
        self.queue.append(action_obj)
        return action_obj
