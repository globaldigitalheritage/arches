"""
ARCHES - a program developed to inventory and manage immovable cultural heritage.
Copyright (C) 2013 J. Paul Getty Trust and World Monuments Fund

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU Affero General Public License as
published by the Free Software Foundation, either version 3 of the
License, or (at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
GNU Affero General Public License for more details.

You should have received a copy of the GNU Affero General Public License
along with this program. If not, see <http://www.gnu.org/licenses/>.
"""

import uuid
import importlib
import datetime
from pprint import pprint
from time import time
from uuid import UUID
from django.db import transaction
from django.db.models import Q
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import ugettext as _
from arches.app.models import models
from arches.app.models.models import EditLog
from arches.app.models.models import TileModel
from arches.app.models.concept import get_preflabel_from_valueid
from arches.app.models.system_settings import settings
from arches.app.search.search_engine_factory import SearchEngineFactory
from arches.app.search.elasticsearch_dsl_builder import Query, Bool, Terms
from arches.app.utils import import_class_from_string
from arches.app.utils.betterJSONSerializer import JSONSerializer, JSONDeserializer
from arches.app.utils.exceptions import (
    InvalidNodeNameException,
    MultipleNodesFoundException,
)
from arches.app.datatypes.datatypes import DataTypeFactory


class Resource(models.ResourceInstance):
    class Meta:
        proxy = True

    def __init__(self, *args, **kwargs):
        super(Resource, self).__init__(*args, **kwargs)
        # from models.ResourceInstance
        # self.resourceinstanceid
        # self.graph
        # self.resourceinstancesecurity
        # end from models.ResourceInstance
        self.tiles = []

    def get_descriptor(self, descriptor):
        module = importlib.import_module("arches.app.functions.primary_descriptors")
        PrimaryDescriptorsFunction = getattr(module, "PrimaryDescriptorsFunction")()
        functionConfig = models.FunctionXGraph.objects.filter(
            graph_id=self.graph_id, function__functiontype="primarydescriptors"
        )
        if len(functionConfig) == 1:
            return PrimaryDescriptorsFunction.get_primary_descriptor_from_nodes(
                self, functionConfig[0].config[descriptor]
            )
        else:
            return "undefined"

    @property
    def displaydescription(self):
        return self.get_descriptor("description")

    @property
    def map_popup(self):
        return self.get_descriptor("map_popup")

    @property
    def displayname(self):
        return self.get_descriptor("name")

    def save_edit(self, user={}, note="", edit_type=""):
        timestamp = datetime.datetime.now()
        edit = EditLog()
        edit.resourceclassid = self.graph_id
        edit.resourceinstanceid = self.resourceinstanceid
        edit.userid = getattr(user, "id", "")
        edit.user_email = getattr(user, "email", "")
        edit.user_firstname = getattr(user, "first_name", "")
        edit.user_lastname = getattr(user, "last_name", "")
        edit.note = note
        edit.timestamp = timestamp
        edit.edittype = edit_type
        edit.save()

    def save(self, *args, **kwargs):
        """
        Saves and indexes a single resource

        """
        graph = models.GraphModel.objects.get(graphid=self.graph_id)
        if graph.isactive is False:
            message = _("This model is not yet active; unable to save.")
            raise ModelInactiveError(message)
        request = kwargs.pop("request", None)
        user = kwargs.pop("user", None)
        super(Resource, self).save(*args, **kwargs)
        for tile in self.tiles:
            tile.resourceinstance_id = self.resourceinstanceid
            saved_tile = tile.save(request=request, index=False)
        if request is None:
            if user is None:
                user = {}
        else:
            user = request.user

        self.save_edit(user=user, edit_type="create")
        self.index()

    def get_root_ontology(self):
        """
        Finds and returns the ontology class of the instance's root node

        """
        root_ontology_class = None
        graph_nodes = models.Node.objects.filter(graph_id=self.graph_id).filter(
            istopnode=True
        )
        if len(graph_nodes) > 0:
            root_ontology_class = graph_nodes[0].ontologyclass

        return root_ontology_class

    def load_tiles(self):
        """
        Loads the resource's tiles array with all the tiles from the database as a flat list

        """

        self.tiles = list(models.TileModel.objects.filter(resourceinstance=self))

    # # flatten out the nested tiles into a single array
    def get_flattened_tiles(self):
        tiles = []
        for tile in self.tiles:
            tiles.extend(tile.get_flattened_tiles())
        return tiles

    @staticmethod
    def bulk_save(resources, primaryDescriptorsFunctionConfig, graph_nodes):
        """
        Saves and indexes a list of resources

        Arguments:
        resources -- a list of resource models

        """
        start = time()

        print("saving resource to db")

        se = SearchEngineFactory().create()
        datatype_factory = DataTypeFactory()
        node_datatypes = {
            str(nodeid): datatype
            for nodeid, datatype in models.Node.objects.values_list(
                "nodeid", "datatype"
            )
        }
        tiles = []
        documents = []
        term_list = []

        start = time()

        for resource in resources:
            resource.tiles = resource.get_flattened_tiles()
            tiles.extend(resource.tiles)

        print("time to extend tiles: %s" % datetime.timedelta(seconds=time() - start))
        start = time()

        # need to save the models first before getting the documents for index
        Resource.objects.bulk_create(resources)
        TileModel.objects.bulk_create(tiles)

        print(
            "time to bulk create tiles and resources: %s"
            % datetime.timedelta(seconds=time() - start)
        )
        start = time()

        for resource in resources:
            resource.save_edit(edit_type="create")

        resources[0].tiles[0].save_edit(
            note=f"bulk created: {len(tiles)} for {len(resources)} resources.", edit_type="bulk_create"
        )

        print(
            "time to save resource edits: %s"
            % datetime.timedelta(seconds=time() - start)
        )
        start = time()

        time_to_get_docs = 0
        time_to_get_root_ontology = 0
        time_to_create_bulk_docs = 0
        time_to_create_bulk_term_docs = 0
        timers = {"timer": 0, "timer1": 0, "timer2": 0, "timer3": 0, "timer4": 0}
        for resource in resources:
            s = time()
            document, terms = resource.get_documents_to_index(
                fetchTiles=False,
                datatype_factory=datatype_factory,
                node_datatypes=node_datatypes,
                config=primaryDescriptorsFunctionConfig,
                graph_nodes=graph_nodes,
            )
            time_to_get_docs = time_to_get_docs + (time() - s)
            # s = time()
            # #document['root_ontology_class'] = resource.get_root_ontology()
            # time_to_get_root_ontology = time_to_get_root_ontology + (time()-s)
            s = time()
            documents.append(
                se.create_bulk_item(
                    index="resources", id=document["resourceinstanceid"], data=document
                )
            )
            time_to_create_bulk_docs = time_to_create_bulk_docs + (time() - s)
            s = time()
            for term in terms:
                term_list.append(
                    se.create_bulk_item(
                        index="terms", id=term["_id"], data=term["_source"]
                    )
                )
            time_to_create_bulk_term_docs = time_to_create_bulk_term_docs + (time() - s)

        # print("timer: %s" % datetime.timedelta(seconds=timers['timer'])
        # print("timer1: %s" % datetime.timedelta(seconds=timers['timer1'])
        # print("timer2: %s" % datetime.timedelta(seconds=timers['timer2'])
        # print("timer3: %s" % datetime.timedelta(seconds=timers['timer3'])
        # print("timer4: %s" % datetime.timedelta(seconds=timers['timer4'])
        # print("time to get documents to index: %s" % datetime.timedelta(seconds=time_to_get_docs)
        # print("time to get root ontology: %s" % datetime.timedelta(seconds=time_to_get_root_ontology)
        # print("time to create bulk docs: %s" % datetime.timedelta(seconds=time_to_create_bulk_docs)
        # print("time to create bulk term docs: %s" % datetime.timedelta(seconds=time_to_create_bulk_term_docs)
        start = time()

        if not settings.STREAMLINE_IMPORT:
            for tile in tiles:
                tile.save_edit(edit_type="tile create", new_value=tile.data)

        # print("time to save tile edits: %s" % datetime.timedelta(seconds=time() - start)
        start = time()

        # print("time to save resources to db:%s" % datetime.timedelta(seconds=time() - start)
        start = time()
        # bulk index the resources, tiles and terms

        # print(documents[0]
        se.bulk_index(documents)
        se.bulk_index(term_list)
        # print("time to index resources:%s" % datetime.timedelta(seconds=time() - start)

    def index(self):
        """
        Indexes all the nessesary items values of a resource to support search

        """
        if str(self.graph_id) != str(settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID):
            se = SearchEngineFactory().create()
            datatype_factory = DataTypeFactory()
            node_datatypes = {
                str(nodeid): datatype
                for nodeid, datatype in models.Node.objects.values_list(
                    "nodeid", "datatype"
                )
            }
            document, terms = self.get_documents_to_index(
                datatype_factory=datatype_factory, node_datatypes=node_datatypes
            )
            document["root_ontology_class"] = self.get_root_ontology()
            doc = JSONSerializer().serializeToPython(document)
            se.index_data(index="resources", body=doc, id=self.pk)
            for term in terms:
                se.index_data("terms", body=term["_source"], id=term["_id"])

    def get_documents_to_index(
        self,
        fetchTiles=True,
        datatype_factory=None,
        node_datatypes=None,
        config=None,
        graph_nodes=None,
    ):
        """
        Gets all the documents nessesary to index a single resource
        returns a tuple of a document and list of terms

        Keyword Arguments:
        fetchTiles -- instead of fetching the tiles from the database get them off the model itself
        datatype_factory -- refernce to the DataTypeFactory instance
        node_datatypes -- a dictionary of datatypes keyed to node ids

        """

        s = time()

        if settings.STREAMLINE_IMPORT:
            document = {}
            document["displaydescription"] = None
            document["resourceinstanceid"] = str(self.resourceinstanceid)
            document["graph_id"] = str(self.graph.pk)
            document["map_popup"] = None
            document["displayname"] = None
            document["root_ontology_class"] = self.get_root_ontology()
            document["legacyid"] = self.legacyid
        else:
            document = JSONSerializer().serializeToPython(self)
        # timers['timer4'] = timers['timer4'] + (time()-s)

        tiles = (
            list(models.TileModel.objects.filter(resourceinstance=self))
            if fetchTiles
            else self.tiles
        )
        document["tiles"] = tiles
        document["strings"] = []
        document["dates"] = []
        document["domains"] = []
        document["geometries"] = []
        document["points"] = []
        document["numbers"] = []
        document["date_ranges"] = []
        document["ids"] = []
        document["provisional_resource"] = (
            "true" if sum([len(t.data) for t in tiles]) == 0 else "false"
        )

        terms = []

        for tile in document["tiles"]:
            for nodeid, nodevalue in tile.data.items():
                datatype = node_datatypes[nodeid]
                if (
                    nodevalue != ""
                    and nodevalue != []
                    and nodevalue != {}
                    and nodevalue is not None
                ):
                    s = time()
                    datatype_instance = datatype_factory.get_instance(datatype)
                    # timers['timer'] = timers['timer'] + (time()-s)

                    if config is not None and str(tile.nodegroup_id) in config:
                        if "name" in config[tile.nodegroup_id]:
                            node = graph_nodes[nodeid]
                            value = datatype_instance.get_display_value(tile, node)
                            if document["displayname"] is None:
                                document["displayname"] = config[tile.nodegroup_id][
                                    "name"
                                ]
                            document["displayname"] = document["displayname"].replace(
                                "<%s>" % node.name, value
                            )
                        if "description" in config[tile.nodegroup_id]:
                            node = graph_nodes[nodeid]
                            value = datatype_instance.get_display_value(tile, node)
                            if document["displaydescription"] is None:
                                document["displaydescription"] = config[
                                    tile.nodegroup_id
                                ]["description"]
                            document["displaydescription"] = document[
                                "displaydescription"
                            ].replace("<%s>" % node.name, value)
                        if "map_popup" in config[tile.nodegroup_id]:
                            node = graph_nodes[nodeid]
                            value = datatype_instance.get_display_value(tile, node)
                            if document["map_popup"] is None:
                                document["map_popup"] = config[tile.nodegroup_id][
                                    "map_popup"
                                ]
                            document["map_popup"] = document["map_popup"].replace(
                                "<%s>" % node.name, value
                            )
                    s = time()
                    datatype_instance.append_to_document(
                        document, nodevalue, nodeid, tile
                    )
                    # timers['timer1'] = timers['timer1'] + (time()-s)
                    s = time()
                    node_terms = datatype_instance.get_search_terms(nodevalue, nodeid)
                    # timers['timer2'] = timers['timer2'] + (time()-s)
                    s = time()
                    for index, term in enumerate(node_terms):
                        terms.append(
                            {
                                "_id": str(nodeid) + str(tile.tileid) + str(index),
                                "_source": {
                                    "value": term,
                                    "nodeid": nodeid,
                                    "nodegroupid": tile.nodegroup_id,
                                    "tileid": tile.tileid,
                                    "resourceinstanceid": tile.resourceinstance_id,
                                    "provisional": False,
                                },
                            }
                        )
                    # timers['timer3'] = timers['timer3'] + (time()-s)

            if tile.provisionaledits is not None:
                provisionaledits = tile.provisionaledits
                if len(provisionaledits) > 0:
                    if document["provisional_resource"] == "false":
                        document["provisional_resource"] = "partial"
                    for user, edit in provisionaledits.items():
                        if edit["status"] == "review":
                            for nodeid, nodevalue in edit["value"].items():
                                datatype = node_datatypes[nodeid]
                                if (
                                    nodevalue != ""
                                    and nodevalue != []
                                    and nodevalue != {}
                                    and nodevalue is not None
                                ):
                                    datatype_instance = datatype_factory.get_instance(
                                        datatype
                                    )
                                    datatype_instance.append_to_document(
                                        document, nodevalue, nodeid, tile, True
                                    )
                                    node_terms = datatype_instance.get_search_terms(
                                        nodevalue, nodeid
                                    )
                                    for index, term in enumerate(node_terms):
                                        terms.append(
                                            {
                                                "_id": str(nodeid)
                                                + str(tile.tileid)
                                                + str(index),
                                                "_source": {
                                                    "value": term,
                                                    "nodeid": nodeid,
                                                    "nodegroupid": tile.nodegroup_id,
                                                    "tileid": tile.tileid,
                                                    "resourceinstanceid": tile.resourceinstance_id,
                                                    "provisional": True,
                                                },
                                            }
                                        )

        return document, terms

    def delete(self, user={}, note=""):
        """
        Deletes a single resource and any related indexed data

        """

        permit_deletion = False
        graph = models.GraphModel.objects.get(graphid=self.graph_id)
        if graph.isactive is False:
            message = _("This model is not yet active; unable to delete.")
            raise ModelInactiveError(message)
        if user != {}:
            user_is_reviewer = user.groups.filter(name="Resource Reviewer").exists()
            if user_is_reviewer is False:
                tiles = list(models.TileModel.objects.filter(resourceinstance=self))
                resource_is_provisional = (
                    True if sum([len(t.data) for t in tiles]) == 0 else False
                )
                if resource_is_provisional is True:
                    permit_deletion = True
            else:
                permit_deletion = True
        else:
            permit_deletion = True

        if permit_deletion is True:
            se = SearchEngineFactory().create()
            related_resources = self.get_related_resources(
                lang="en-US", start=0, limit=1000, page=0
            )
            for rr in related_resources["resource_relationships"]:
                models.ResourceXResource.objects.get(pk=rr["resourcexid"]).delete()
            query = Query(se)
            bool_query = Bool()
            bool_query.filter(
                Terms(field="resourceinstanceid", terms=[self.resourceinstanceid])
            )
            query.add_query(bool_query)
            results = query.search(index="terms")["hits"]["hits"]
            for result in results:
                se.delete(index="terms", id=result["_id"])
            se.delete(index="resources", id=self.resourceinstanceid)

            self.save_edit(edit_type="delete", user=user, note=self.displayname)
            super(Resource, self).delete()

        return permit_deletion

    def get_related_resources(
        self,
        lang="en-US",
        limit=settings.RELATED_RESOURCES_EXPORT_LIMIT,
        start=0,
        page=0,
    ):
        """
        Returns an object that lists the related resources, the relationship types, and a reference to the current resource

        """
        graphs = (
            models.GraphModel.objects.all()
            .exclude(pk=settings.SYSTEM_SETTINGS_RESOURCE_MODEL_ID)
            .exclude(isresource=False)
            .exclude(isactive=False)
        )
        graph_lookup = {
            str(graph.graphid): {
                "name": graph.name,
                "iconclass": graph.iconclass,
                "fillColor": graph.color,
            }
            for graph in graphs
        }
        ret = {
            "resource_instance": self,
            "resource_relationships": [],
            "related_resources": [],
            "node_config_lookup": graph_lookup,
        }
        se = SearchEngineFactory().create()

        if page > 0:
            limit = settings.RELATED_RESOURCES_PER_PAGE
            start = limit * int(page - 1)

        def get_relations(resourceinstanceid, start, limit):
            query = Query(se, start=start, limit=limit)
            bool_filter = Bool()
            bool_filter.should(
                Terms(field="resourceinstanceidfrom", terms=resourceinstanceid)
            )
            bool_filter.should(
                Terms(field="resourceinstanceidto", terms=resourceinstanceid)
            )
            query.add_query(bool_filter)
            return query.search(index="resource_relations")

        resource_relations = get_relations(self.resourceinstanceid, start, limit)
        ret["total"] = resource_relations["hits"]["total"]
        instanceids = set()

        for relation in resource_relations["hits"]["hits"]:
            try:
                preflabel = get_preflabel_from_valueid(
                    relation["_source"]["relationshiptype"], lang
                )
                relation["_source"]["relationshiptype_label"] = preflabel["value"]
            except:
                relation["_source"]["relationshiptype_label"] = relation["_source"][
                    "relationshiptype"
                ]

            ret["resource_relationships"].append(relation["_source"])
            instanceids.add(relation["_source"]["resourceinstanceidto"])
            instanceids.add(relation["_source"]["resourceinstanceidfrom"])
        if len(instanceids) > 0:
            instanceids.remove(str(self.resourceinstanceid))

        if len(instanceids) > 0:
            related_resources = se.search(index="resources", id=list(instanceids))
            if related_resources:
                for resource in related_resources["docs"]:
                    relations = get_relations(resource["_id"], 0, 0)
                    resource["_source"]["total_relations"] = relations["hits"]["total"]
                    ret["related_resources"].append(resource["_source"])
        return ret

    def copy(self):
        """
        Returns a copy of this resource instance includeing a copy of all tiles associated with this resource instance

        """
        # need this here to prevent a circular import error
        from arches.app.models.tile import Tile

        id_map = {}
        new_resource = Resource()
        new_resource.graph = self.graph

        if len(self.tiles) == 0:
            self.tiles = Tile.objects.filter(resourceinstance=self)

        for tile in self.tiles:
            new_tile = Tile()
            new_tile.data = tile.data
            new_tile.nodegroup = tile.nodegroup
            new_tile.parenttile = tile.parenttile
            new_tile.resourceinstance = new_resource
            new_tile.sortorder = tile.sortorder

            new_resource.tiles.append(new_tile)
            id_map[tile.pk] = new_tile

        for tile in new_resource.tiles:
            if tile.parenttile:
                tile.parenttile = id_map[tile.parenttile_id]

        with transaction.atomic():
            new_resource.save()

        return new_resource

    def serialize(self, fields=None, exclude=None):
        """
        Serialize to a different form then used by the internal class structure

        used to append additional values (like parent ontology properties) that
        internal objects (like models.Nodes) don't support

        """

        ret = JSONSerializer().handle_model(self)
        ret["tiles"] = self.tiles

        return JSONSerializer().serializeToPython(ret)

    def get_node_values(self, node_name):
        """
        Take a node_name (string) as an argument and return a list of values.
        If an invalid node_name is used, or if multiple nodes with the same
        name are found, the method returns False.
        Current supported (tested) node types are: string, date, concept, geometry
        """

        nodes = models.Node.objects.filter(name=node_name, graph_id=self.graph_id)

        if len(nodes) > 1:
            raise MultipleNodesFoundException(node_name, nodes)

        if len(nodes) == 0:
            raise InvalidNodeNameException(node_name)

        tiles = self.tilemodel_set.filter(nodegroup_id=nodes[0].nodegroup_id)

        values = []
        for tile in tiles:
            for node_id, value in tile.data.items():
                if node_id == str(nodes[0].nodeid):
                    if type(value) is list:
                        for v in value:
                            values.append(parse_node_value(v))
                    else:
                        values.append(parse_node_value(value))

        return values


def parse_node_value(value):
    if is_uuid(value):
        try:
            return models.Value.objects.get(pk=value).value
        except ObjectDoesNotExist:
            pass
    return value


def is_uuid(value_to_test):
    try:
        UUID(value_to_test)
        return True
    except:
        return False


class ModelInactiveError(Exception):
    def __init__(self, message, code=None):
        self.title = _("Model Inactive Error")
        self.message = message
        self.code = code

    def __str__(self):
        return repr(self.message)
