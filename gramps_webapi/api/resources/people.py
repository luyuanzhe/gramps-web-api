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

from flask import abort
from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.lib import Person
from gramps.gen.utils.grampslocale import GrampsLocale

from ...auth.const import PERM_VIEW_PERSON
from ..auth import require_permissions
from ..blueprint import api_blueprint
from .base import (
    GrampsObjectProtectedResource,
    GrampsObjectResourceHelper,
    GrampsObjectsProtectedResource,
    ProtectedResource,
)
from .emit import GrampsJSONEncoder
from .schemas import PersonRelativesStatsSchema
from .util import (
    get_extended_attributes,
    get_family_by_handle,
    get_person_profile_for_object,
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


class PersonRelativesStatsResource(ProtectedResource, GrampsJSONEncoder):
    """Person relatives stats resource."""

    @api_blueprint.response(200, PersonRelativesStatsSchema())
    def get(self, handle: str):
        """Get statistics about a person's relatives."""
        require_permissions([PERM_VIEW_PERSON])
        db_handle = self.db_handle

        try:
            person = db_handle.get_person_from_handle(handle)
        except Exception:
            abort(404)

        if not person:
            abort(404)

        parents = set()
        siblings = set()
        spouses = set()
        children = set()
        grandparents = set()
        grandchildren = set()

        # Parents and immediate siblings from parent families
        for family_handle in person.parent_family_list:
            try:
                family = db_handle.get_family_from_handle(family_handle)
            except Exception:
                continue
            if not family:
                continue
            if family.father_handle:
                parents.add(family.father_handle)
            if family.mother_handle:
                parents.add(family.mother_handle)
            for child_ref in family.child_ref_list:
                if child_ref.ref != person.handle:
                    siblings.add(child_ref.ref)

        # Siblings (including half-siblings)
        for parent_handle in parents:
            try:
                parent = db_handle.get_person_from_handle(parent_handle)
            except Exception:
                continue
            if not parent:
                continue
            for family_handle in parent.family_list:
                try:
                    family = db_handle.get_family_from_handle(family_handle)
                except Exception:
                    continue
                if not family:
                    continue
                for child_ref in family.child_ref_list:
                    if child_ref.ref != person.handle:
                        siblings.add(child_ref.ref)

        # Spouses and Children
        for family_handle in person.family_list:
            try:
                family = db_handle.get_family_from_handle(family_handle)
            except Exception:
                continue
            if not family:
                continue
            if family.father_handle and family.father_handle != person.handle:
                spouses.add(family.father_handle)
            if family.mother_handle and family.mother_handle != person.handle:
                spouses.add(family.mother_handle)
            for child_ref in family.child_ref_list:
                children.add(child_ref.ref)

        # Grandparents
        for parent_handle in parents:
            try:
                parent = db_handle.get_person_from_handle(parent_handle)
            except Exception:
                continue
            if not parent:
                continue
            for family_handle in parent.parent_family_list:
                try:
                    family = db_handle.get_family_from_handle(family_handle)
                except Exception:
                    continue
                if not family:
                    continue
                if family.father_handle:
                    grandparents.add(family.father_handle)
                if family.mother_handle:
                    grandparents.add(family.mother_handle)

        # Grandchildren
        for child_handle in children:
            try:
                child = db_handle.get_person_from_handle(child_handle)
            except Exception:
                continue
            if not child:
                continue
            for family_handle in child.family_list:
                try:
                    family = db_handle.get_family_from_handle(family_handle)
                except Exception:
                    continue
                if not family:
                    continue
                for child_ref in family.child_ref_list:
                    grandchildren.add(child_ref.ref)

        all_relatives = parents | siblings | spouses | children | grandparents | grandchildren
        all_relatives.discard(person.handle)

        payload = {
            "total_relatives": len(all_relatives),
            "parents": len(parents),
            "siblings": len(siblings),
            "spouses": len(spouses),
            "children": len(children),
            "grandparents": len(grandparents),
            "grandchildren": len(grandchildren)
        }

        return self.response(200, payload)
