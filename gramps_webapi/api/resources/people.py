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

from gramps.gen.const import GRAMPS_LOCALE as glocale
from gramps.gen.errors import HandleError
from gramps.gen.lib import Family, Person
from gramps.gen.utils.grampslocale import GrampsLocale

from ...auth.const import PERM_VIEW_PERSON
from ..auth import require_permissions
from ..blueprint import api_blueprint
from ..cache import request_cache_decorator
from ..util import abort_with_message, get_db_handle
from . import ProtectedResource
from .base import (
    GrampsObjectProtectedResource,
    GrampsObjectResourceHelper,
    GrampsObjectsProtectedResource,
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


class PersonRelativesStatsResource(ProtectedResource, GrampsJSONEncoder):
    """Person relatives stats resource."""

    @api_blueprint.response(200, PersonRelativesStatsSchema())
    @request_cache_decorator
    def get(self, handle: str):
        """Get counts of relatives for a person."""
        require_permissions([PERM_VIEW_PERSON])
        db_handle = get_db_handle()
        person = self._get_person_or_404(db_handle, handle)

        parents = self._get_parent_handles(db_handle, person)
        siblings = self._get_sibling_handles(db_handle, person)
        spouses = self._get_spouse_handles(db_handle, person)
        children = self._get_child_handles(db_handle, person)
        grandparents = self._get_grandparent_handles(db_handle, parents)
        grandchildren = self._get_grandchild_handles(db_handle, children)

        for relative_handles in [
            parents,
            siblings,
            spouses,
            children,
            grandparents,
            grandchildren,
        ]:
            relative_handles.discard(person.handle)

        total_relatives = set().union(
            parents,
            siblings,
            spouses,
            children,
            grandparents,
            grandchildren,
        )

        return self.response(
            200,
            {
                "total_relatives": len(total_relatives),
                "parents": len(parents),
                "siblings": len(siblings),
                "spouses": len(spouses),
                "children": len(children),
                "grandparents": len(grandparents),
                "grandchildren": len(grandchildren),
            },
        )

    @staticmethod
    def _get_person_or_404(db_handle, handle: str) -> Person:
        try:
            person = db_handle.get_person_from_handle(handle)
        except HandleError:
            abort_with_message(404, "Person not found")
        if person is None:
            abort_with_message(404, "Person not found")
            raise AssertionError
        return person

    @staticmethod
    def _get_family_handles(person: Person) -> list[str]:
        return list(person.get_family_handle_list())

    @staticmethod
    def _get_parent_family_handles(person: Person) -> list[str]:
        return list(person.get_parent_family_handle_list())

    @staticmethod
    def _get_family(db_handle, handle: str) -> Family | None:
        try:
            return db_handle.get_family_from_handle(handle)
        except HandleError:
            return None

    @classmethod
    def _get_parent_handles(cls, db_handle, person: Person) -> set[str]:
        handles = set()
        for family_handle in cls._get_parent_family_handles(person):
            family = cls._get_family(db_handle, family_handle)
            if family is None:
                continue
            father_handle = family.get_father_handle()
            mother_handle = family.get_mother_handle()
            if father_handle:
                handles.add(father_handle)
            if mother_handle:
                handles.add(mother_handle)
        handles.discard(person.handle)
        return handles

    @classmethod
    def _get_sibling_handles(cls, db_handle, person: Person) -> set[str]:
        handles = set()
        for family_handle in cls._get_parent_family_handles(person):
            family = cls._get_family(db_handle, family_handle)
            if family is None:
                continue
            handles.update(
                ref.ref for ref in family.get_child_ref_list() if ref.ref and ref.ref != person.handle
            )
        return handles

    @classmethod
    def _get_spouse_handles(cls, db_handle, person: Person) -> set[str]:
        handles = set()
        for family_handle in cls._get_family_handles(person):
            family = cls._get_family(db_handle, family_handle)
            if family is None:
                continue
            for spouse_handle in [family.get_father_handle(), family.get_mother_handle()]:
                if spouse_handle and spouse_handle != person.handle:
                    handles.add(spouse_handle)
        return handles

    @classmethod
    def _get_child_handles(cls, db_handle, person: Person) -> set[str]:
        handles = set()
        for family_handle in cls._get_family_handles(person):
            family = cls._get_family(db_handle, family_handle)
            if family is None:
                continue
            handles.update(ref.ref for ref in family.get_child_ref_list() if ref.ref)
        handles.discard(person.handle)
        return handles

    @classmethod
    def _get_grandparent_handles(cls, db_handle, parent_handles: set[str]) -> set[str]:
        handles = set()
        for parent_handle in parent_handles:
            try:
                parent = db_handle.get_person_from_handle(parent_handle)
            except HandleError:
                continue
            if parent is None:
                continue
            handles.update(cls._get_parent_handles(db_handle, parent))
        return handles

    @classmethod
    def _get_grandchild_handles(cls, db_handle, child_handles: set[str]) -> set[str]:
        handles = set()
        for child_handle in child_handles:
            try:
                child = db_handle.get_person_from_handle(child_handle)
            except HandleError:
                continue
            if child is None:
                continue
            handles.update(cls._get_child_handles(db_handle, child))
        return handles


class PeopleResource(GrampsObjectsProtectedResource, PersonResourceHelper):
    """People resource."""
