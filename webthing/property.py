"""High-level Property base class implementation."""

from copy import deepcopy
from jsonschema import validate
from jsonschema.exceptions import ValidationError

from .errors import PropertyError
from .value import Value


class Property:
    """A Property represents an individual state value of a thing."""

    def __init__(
        self,
        thing,
        name,
        value,
        metadata=None,
        content_type="application/json",
    ):
        """
        Initialize the object.
        thing -- the Thing this property belongs to
        name -- name of the property
        value -- Value object to hold the property value
        metadata -- property metadata, i.e. type, description, unit, etc.,
                    as a dict
        """
        self.value = value
        self.thing = thing
        self.name = name
        self.href_prefix = ""
        self.href = "/properties/{}".format(self.name)
        self.metadata = metadata if metadata is not None else {}
        self.content_type = content_type

        # Add the property change observer to notify the Thing about a property
        # change.
        self.value.on("update", lambda _: self.thing.property_notify(self))

    def validate_value(self, value):
        """
        Validate new property value before setting it.

        value -- New value
        """
        if "readOnly" in self.metadata and self.metadata["readOnly"]:
            raise PropertyError("Read-only property")

        try:
            validate(value, self.metadata)
        except ValidationError:
            raise PropertyError("Invalid property value")

    def as_property_description(self):
        """
        Get the property description.

        Returns a dictionary describing the property.
        """
        description = deepcopy(self.metadata)

        # Imply readonly if not explicitly given
        if "readOnly" not in description and self.value.readonly:
            description["readOnly"] = True

        # Create forms
        if "forms" not in description:
            description["forms"] = []

        description["forms"].append(
            {
                "op": "readproperty",
                "href": self.href_prefix + self.href,
                "contentType": self.content_type,
                "htv:methodName": "GET",
            }
        )

        if not description.get("readOnly", False):
            description["forms"].append(
                {
                    "op": "writeproperty",
                    "href": self.href_prefix + self.href,
                    "contentType": self.content_type,
                    "htv:methodName": "PUT",
                }
            )

        return description

    def set_href_prefix(self, prefix):
        """
        Set the prefix of any hrefs associated with this property.

        prefix -- the prefix
        """
        self.href_prefix = prefix

    def get_href(self):
        """
        Get the href of this property.

        Returns the href.
        """
        return self.href_prefix + self.href

    async def get_value(self):
        """
        Get the current property value.

        Returns the value.
        """
        return await self.value.get()

    async def set_value(self, value):
        """
        Set the current value of the property.

        value -- the value to set
        """
        self.validate_value(value)
        await self.value.set(value)

    def get_name(self):
        """
        Get the name of this property.

        Returns the name.
        """
        return self.name

    def get_thing(self):
        """Get the thing associated with this property."""
        return self.thing

    def get_metadata(self):
        """Get the metadata associated with this property."""
        return self.metadata

    def get_content_type(self):
        """Get the content type of this property."""
        return self.content_type
