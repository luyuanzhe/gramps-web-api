#
# Gramps Web API - A RESTful API for the Gramps genealogy program
#
# Copyright (C) 2020      David Straub
# Copyright (C) 2020      Christopher Horn
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
#

"""Person API resource."""

from typing import Dict

from flask import Response, abort
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.lib import Person
from gramps.gen.utils.grampslocale import GrampsLocale
from marshmallow import Schema
from webargs import fields, validate

from ...types import Handle
from ..blueprint import api_blueprint
from ..util import get_db_handle
from . import ProtectedResource
from .base import (
    GrampsObjectProtectedResource,
    GrampsObjectResourceHelper,
    GrampsObjectsProtectedResource,
)
from .emit import GrampsJSONEncoder
from .schemas import RelativeStatsSchema
from .util import (
    get_extended_attributes,
    get_family_by_handle,
    get_person_by_handle,
    get_person_profile_for_object,
)


def _get_parent_handles(db_handle, person: Person):
    """Get handles of parents from primary parent family."""
    parents = set()
    primary_family_handle = person.get_main_parents_family_handle()
    if primary_family_handle:
        family = get_family_by_handle(db_handle, primary_family_handle)
        if family and not isinstance(family, dict):
            if family.father_handle:
                parents.add(family.father_handle)
            if family.mother_handle:
                parents.add(family.mother_handle)
    return parents


def _get_sibling_handles(db_handle, person: Person):
    """Get handles of siblings (excluding self)."""
    siblings = set()
    for family_handle in person.parent_family_list:
        family = get_family_by_handle(db_handle, family_handle)
        if family and not isinstance(family, dict):
            for child_ref in family.child_ref_list:
                if child_ref.ref != person.handle:
                    siblings.add(child_ref.ref)
    return siblings


def _get_spouse_handles(db_handle, person: Person):
    """Get handles of spouses from family_list."""
    spouses = set()
    for family_handle in person.family_list:
        family = get_family_by_handle(db_handle, family_handle)
        if family and not isinstance(family, dict):
            if family.father_handle and family.father_handle != person.handle:
                spouses.add(family.father_handle)
            if family.mother_handle and family.mother_handle != person.handle:
                spouses.add(family.mother_handle)
    return spouses


def _get_child_handles(db_handle, person: Person):
    """Get handles of children from family_list."""
    children = set()
    for family_handle in person.family_list:
        family = get_family_by_handle(db_handle, family_handle)
        if family and not isinstance(family, dict):
            for child_ref in family.child_ref_list:
                children.add(child_ref.ref)
    return children


def _get_grandparent_handles(db_handle, person: Person):
    """Get handles of grandparents (parents of parents)."""
    grandparents = set()
    parent_handles = _get_parent_handles(db_handle, person)
    for parent_handle in parent_handles:
        parent = get_person_by_handle(db_handle, parent_handle)
        if parent and not isinstance(parent, dict):
            gp_handles = _get_parent_handles(db_handle, parent)
            grandparents.update(gp_handles)
    return grandparents


def _get_grandchild_handles(db_handle, person: Person):
    """Get handles of grandchildren (children of children)."""
    grandchildren = set()
    child_handles = _get_child_handles(db_handle, person)
    for child_handle in child_handles:
        child = get_person_by_handle(db_handle, child_handle)
        if child and not isinstance(child, dict):
            gc_handles = _get_child_handles(db_handle, child)
            grandchildren.update(gc_handles)
    return grandchildren


class RelativeStatsQueryArgs(Schema):
    """Query arguments for relative stats endpoint."""

    include_self = fields.Boolean(
        load_default=False,
        metadata={
            "description": "If true, include the person themselves in total_relatives count."
        },
    )


class PersonRelativeStatsResource(ProtectedResource, GrampsJSONEncoder):
    """Relative statistics resource for a person."""

    @api_blueprint.response(200, RelativeStatsSchema())
    @api_blueprint.arguments(RelativeStatsQueryArgs, location="query")
    def get(self, args: Dict, handle: Handle) -> Response:
        """Get relative count statistics for a person."""
        db_handle = get_db_handle()
        person = get_person_by_handle(db_handle, handle)
        if person == {}:
            abort(404)

        parent_handles = _get_parent_handles(db_handle, person)
        sibling_handles = _get_sibling_handles(db_handle, person)
        spouse_handles = _get_spouse_handles(db_handle, person)
        child_handles = _get_child_handles(db_handle, person)
        grandparent_handles = _get_grandparent_handles(db_handle, person)
        grandchild_handles = _get_grandchild_handles(db_handle, person)

        all_relatives = set()
        all_relatives.update(parent_handles)
        all_relatives.update(sibling_handles)
        all_relatives.update(spouse_handles)
        all_relatives.update(child_handles)
        all_relatives.update(grandparent_handles)
        all_relatives.update(grandchild_handles)

        total = len(all_relatives)
        if args.get("include_self"):
            total += 1

        return self.response(
            200,
            {
                "total_relatives": total,
                "parents": len(parent_handles),
                "siblings": len(sibling_handles),
                "spouses": len(spouse_handles),
                "children": len(child_handles),
                "grandparents": len(grandparent_handles),
                "grandchildren": len(grandchild_handles),
            },
        )



class PersonResourceHelper(GrampsObjectResourceHelper):
    """Person resource helper."""

    gramps_class_name = "Person"

    def object_extend(
        self, obj: Person, args: Dict, locale: GrampsLocale = glocale
    ) -> Person:
        """Extend person attributes as needed."""
        db_handle = self.db_handle
        if "profile" in args:
            obj.profile = get_person_profile_for_object(
                db_handle,
                obj,
                args["profile"],
                locale=locale,
                name_format=args.get("name_format"),
                precision=args.get("precision", 3),
            )
        if "extend" in args:
            obj.extended = get_extended_attributes(db_handle, obj, args)
            if "all" in args["extend"] or "family_list" in args["extend"]:
                obj.extended["families"] = [
                    get_family_by_handle(db_handle, handle)
                    for handle in obj.family_list
                ]
            if "all" in args["extend"] or "parent_family_list" in args["extend"]:
                obj.extended["parent_families"] = [
                    get_family_by_handle(db_handle, handle)
                    for handle in obj.parent_family_list
                ]
            if "all" in args["extend"] or "primary_parent_family" in args["extend"]:
                obj.extended["primary_parent_family"] = get_family_by_handle(
                    db_handle, obj.get_main_parents_family_handle()
                )
        return obj


class PersonResource(GrampsObjectProtectedResource, PersonResourceHelper):
    """Person resource."""


class PeopleResource(GrampsObjectsProtectedResource, PersonResourceHelper):
    """People resource."""
