"""
Biolink Compliance testing support

Ideally, this code should probably reside outside the reasoner-validator project
(in fact, we are shameless copying it over from the SRI Testing translator.biolink package for now)
but until the shared project package publication issues are sorted out, we duplicate it here.

TODO: copied from https://github.com/TranslatorSRI/SRI_testing/blob/main/translator/biolink/__init__.py
      on April 27, 2022 (check for updates or package publication to pypi?)
"""
from typing import Optional, Dict, List, Tuple, Set
from enum import Enum
from functools import lru_cache
from urllib.error import HTTPError
from pprint import PrettyPrinter
import re
import logging

from bmt import Toolkit

logger = logging.getLogger(__name__)

pp = PrettyPrinter(indent=4)

# TODO: is there a better way to ensure that a Biolink Model compliance test
#       runs quickly enough if the knowledge graph is very large?
#       Limiting nodes and edges viewed may miss deeply embedded errors(?)
_MAX_TEST_NODES = 1000
_MAX_TEST_EDGES = 100

# Biolink Release number should be a well-formed Semantic Version
semver_pattern = re.compile(r"^\d+\.\d+\.\d+$")


def _get_biolink_model_schema(biolink_release: Optional[str] = None) -> Optional[str]:
    """
    Get Biolink Model Schema
    """
    if biolink_release:
        if not semver_pattern.fullmatch(biolink_release):
            raise TypeError(
                "The 'biolink_release' argument '"
                + biolink_release
                + "' is not a properly formatted 'major.minor.patch' semantic version?"
            )
        schema = f"https://raw.githubusercontent.com/biolink/biolink-model/{biolink_release}/biolink-model.yaml"
        return schema
    else:
        return None


# At any given time, only a modest number of Biolink Model versions
# are expected to be active targets for SRI Test validations?
@lru_cache(maxsize=3)
def _get_biolink_model_toolkit(biolink_release: Optional[str] = None) -> Toolkit:
    if biolink_release:
        # If errors occur while instantiating non-default Toolkit;
        # then log the error but just use default as a workaround?
        try:
            biolink_schema = _get_biolink_model_schema(biolink_release=biolink_release)
            bmtk = Toolkit(biolink_schema)
            return bmtk
        except (TypeError, HTTPError) as ex:
            logger.error(str(ex))

    return Toolkit()


class TrapiGraphType(Enum):
    Edge_Object = "Edge"
    Query_Graph = "Query Graph"
    Knowledge_Graph = "Knowledge Graph"


class BiolinkValidator:

    def __init__(self, graph_type: TrapiGraphType, biolink_release=None):
        """
        :param graph_type: type of graph data being validated

        """
        self.graph_type = graph_type
        self.bmtk = _get_biolink_model_toolkit(biolink_release=biolink_release)
        self.errors: Set[str] = set()
        self.nodes: Set[str] = set()

    def report_error(self, err_msg):
        self.errors.add(f"{self.graph_type.value} Error: {err_msg}")

    def get_biolink_model_version(self) -> str:
        return self.bmtk.get_model_version()

    def get_result(self) -> Tuple[str, Optional[List[str]]]:
        return self.bmtk.get_model_version(), list(self.errors)

    def validate_category(self, node_id: str, category: str) -> Optional[str]:
        if self.bmtk.is_category(category):
            return self.bmtk.get_element(category).name
        elif self.bmtk.is_mixin(category):
            # finding mixins in the categories is OK, but we otherwise ignore them in validation
            logger.info(f"\nReported Biolink Model category '{category}' resolves to a Biolink Model 'mixin'?")
        else:
            element = self.bmtk.get_element(category)
            if element:
                # got something here... hopefully just an abstract class
                # but not a regular category, so we also ignore it!
                # TODO: how do we better detect abstract classes from the model?
                #       How strict should our validation be here?
                logger.info(
                    f"\nReported Biolink Model category '{category}' " +
                    "resolves to the (possibly abstract) " +
                    f"Biolink Model element '{element.name}'?")
            else:
                # Error: a truly unrecognized category?
                self.report_error(
                    f"'{category}' for node '{node_id}' " +
                    "is not a recognized Biolink Model category?"
                )
        return None

    def validate_node(self, node_id, details):

        logger.debug(f"{node_id}: {str(details)}")

        if self.graph_type is TrapiGraphType.Knowledge_Graph:
            # TODO: this will fail for an earlier TRAPI data schema version
            #       which didn't use the tag 'categories' for nodes...
            #       probably no longer relevant to the community?
            if 'categories' in details:
                if not isinstance(details["categories"], List):
                    self.report_error(f"The value of node '{node_id}.categories' should be an array?")
                else:
                    categories = details["categories"]
                    node_prefix_mapped: bool = False
                    for category in categories:
                        category_name: str = self.validate_category(node_id, category)
                        if category_name:
                            possible_subject_categories = self.bmtk.get_element_by_prefix(node_id)
                            if category_name in possible_subject_categories:
                                node_prefix_mapped = True
                    if not node_prefix_mapped:
                        self.report_error(
                            f"For all node categories [{','.join(categories)}] of " +
                            f"'{node_id}', the CURIE prefix namespace remains unmapped?"
                        )
            else:
                self.report_error(f"Node '{node_id}' is missing its 'categories'?")
            # TODO: Do we need to (or can we) validate other Knowledge Graph node fields here? Perhaps yet?

        else:  # Query Graph node validation

            if "ids" in details:
                ids = details["ids"]
                if not isinstance(ids, List):
                    self.report_error(f"Node '{node_id}.ids' slot value is not an array?")
                elif not ids:
                    self.report_error(f"Node '{node_id}.ids' slot array is empty?")
            else:
                ids: List[str] = list()  # null "ids" value is permitted in QNodes

            if "categories" in details:
                categories = details["categories"]
                if not isinstance(categories, List):
                    self.report_error(f"Node '{node_id}.categories' slot value is not an array?")
                elif not categories:
                    self.report_error(f"Node '{node_id}.categories' slot array is empty?")
                else:
                    id_prefix_mapped: Dict = {identifier: False for identifier in ids}
                    for category in categories:
                        # category validation may report an error internally
                        category_name = self.validate_category(node_id, category)
                        if category_name:
                            for identifier in ids:  # may be empty list if not provided...
                                possible_subject_categories = self.bmtk.get_element_by_prefix(identifier)
                                if category_name in possible_subject_categories:
                                    id_prefix_mapped[identifier] = True
                    unmapped_ids = [
                        identifier for identifier in id_prefix_mapped.keys() if not id_prefix_mapped[identifier]
                    ]
                    if unmapped_ids:
                        self.report_error(
                            f"Node '{node_id}.ids' have {str(unmapped_ids)} " +
                            f"that are unmapped to any of the Biolink Model categories {str(categories)}?")

            # else:  # null "categories" value is permitted in QNodes

            if 'is_set' in details:
                is_set = details["is_set"]
                if not isinstance(is_set, bool):
                    self.report_error(f"Node '{node_id}.is_set' slot is not a boolean value?")
            # else:  # a null "is_set" value is permitted in QNodes but defaults to 'False'

            # constraints  # TODO: how do we validate node constraints?
            pass

    def set_nodes(self, nodes: Set):
        self.nodes.update(nodes)

    def validate_edge(self, edge: Dict):

        logger.debug(edge)

        # edge data fields to be validated...
        subject_id = edge['subject'] if 'subject' in edge else None

        predicates = predicate = None
        if self.graph_type is TrapiGraphType.Knowledge_Graph:
            predicate = edge['predicate'] if 'predicate' in edge else None
            edge_label = predicate
        else:
            # Query Graph...
            predicates = edge['predicates'] if 'predicates' in edge else None
            edge_label = str(predicates)

        object_id = edge['object'] if 'object' in edge else None
        attributes = edge['attributes'] if 'attributes' in edge else None

        edge_id = f"{str(subject_id)}--{edge_label}->{str(object_id)}"

        if not subject_id:
            self.report_error(f"Edge '{edge_id}' has a missing or empty 'subject' slot value?")
        elif subject_id not in self.nodes:
            self.report_error(
                f"Edge 'subject' id '{subject_id}' is missing from the nodes catalog?"
            )

        if self.graph_type is TrapiGraphType.Knowledge_Graph:
            if not predicate:
                self.report_error(f"Edge '{edge_id}' has a missing or empty predicate slot?")
            elif not self.bmtk.is_predicate(predicate):
                self.report_error(f"'{predicate}' is an unknown Biolink Model predicate?")
        else:  # is a Query Graph...
            if predicates is None:
                # Query Graphs can have a missing or null predicates slot
                pass
            elif not isinstance(predicates, List):
                self.report_error(f"Edge '{edge_id}' predicate slot value is not an array?")
            elif len(predicates) is 0:
                self.report_error(f"Edge '{edge_id}' predicate slot value is an empty array?")
            else:
                # Should now be a non-empty list of CURIES which are valid Biolink Predicates
                for predicate in predicates:
                    if not self.bmtk.is_predicate(predicate):
                        self.report_error(f"'{predicate}' is an unknown Biolink Model predicate?")

        if not object_id:
            self.report_error(f"Edge '{edge_id}' has a missing or empty 'object' slot value?")
        elif object_id not in self.nodes:
            self.report_error(f"Edge 'object' id '{object_id}' is missing from the nodes catalog?")

        if self.graph_type is TrapiGraphType.Knowledge_Graph:
            if not attributes:
                # TODO: not quite sure whether and how to fully validate the 'attributes' of an edge
                # For now, we simply assume that *all* edges must have *some* attributes
                # (at least, provenance related, but we don't explicitly test for them)
                self.report_error(f"Edge '{edge_id}' has missing or empty attributes?")
        else:
            # TODO: do we need to validate Query Graph 'constraints' slot contents here?
            pass

    def check_biolink_model_compliance_of_input_edge(self, edge: Dict[str, str]) -> Tuple[str, Optional[List[str]]]:
        """
        Validate a templated test input edge contents against the current BMT Biolink Model release.

        Sample method 'edge' with expected dictionary tags:

        {
            'subject_category': 'biolink:AnatomicalEntity',
            'object_category': 'biolink:AnatomicalEntity',
            'predicate': 'biolink:subclass_of',
            'subject': 'UBERON:0005453',
            'object': 'UBERON:0035769'
        }

        :param edge: basic dictionary of a templated input edge - S-P-O including concept Biolink Model categories

        :returns: 2-tuple of Biolink Model version (str) and List[str] (possibly empty) of error messages
        """
        # data fields to be validated...
        subject_category_curie = edge['subject_category']
        object_category_curie = edge['object_category']
        predicate_curie = edge['predicate']
        subject_curie = edge['subject']
        object_curie = edge['object']

        if self.bmtk.is_category(subject_category_curie):
            subject_category_name = self.bmtk.get_element(subject_category_curie).name
        else:
            err_msg = f"'subject' category '{subject_category_curie}' is unknown?"
            self.report_error(err_msg)
            subject_category_name = None

        if self.bmtk.is_category(object_category_curie):
            object_category_name = self.bmtk.get_element(object_category_curie).name
        else:
            err_msg = f"'object' category '{object_category_curie}' is unknown?"
            self.report_error(err_msg)
            object_category_name = None

        if not self.bmtk.is_predicate(predicate_curie):
            err_msg = f"predicate '{predicate_curie}' is unknown?"
            self.report_error(err_msg)

        if subject_category_name:
            possible_subject_categories = self.bmtk.get_element_by_prefix(subject_curie)
            if subject_category_name not in possible_subject_categories:
                err_msg = f"namespace prefix of 'subject' identifier '{subject_curie}' is unmapped to '{subject_category_curie}'?"
                self.report_error(err_msg)

        if object_category_name:
            possible_object_categories = self.bmtk.get_element_by_prefix(object_curie)
            if object_category_name not in possible_object_categories:
                err_msg = f"namespace prefix of 'object' identifier '{object_curie}' is unmapped to '{object_category_curie}'?"
                self.report_error(err_msg)

        return self.get_result()

    def check_biolink_model_compliance(self, graph: Dict) -> Tuple[str, Optional[List[str]]]:
        """
        Validate a TRAPI-schema compliant Message graph-like data structure
        against the currently active BMT Biolink Model release.
    
        :param graph: knowledge graph to be validated

        :returns: 2-tuple of Biolink Model version (str) and List[str] (possibly empty) of error messages
        """
        # Access graph data fields to be validated
        nodes: Optional[Dict]
        if 'nodes' in graph and graph['nodes']:
            nodes = graph['nodes']
        else:
            # Query Graphs can have an empty nodes catalog
            if self.graph_type is not TrapiGraphType.Query_Graph:
                self.report_error(f"No nodes found?")
            # else:  Query Graphs can omit the 'nodes' tag
            nodes = None

        edges: Optional[Dict]
        if 'edges' in graph and graph['edges']:
            edges = graph['edges']
        else:
            if self.graph_type is not TrapiGraphType.Query_Graph:
                self.report_error(f"No edges found?")
            # else:  Query Graphs can omit the 'edges' tag
            edges = None

        # I only do a sampling of node and edge content. This ensures that
        # the tests are performant but may miss errors deeper inside the graph?
        nodes_seen = 0
        if nodes:
            for node_id, details in nodes.items():

                self.validate_node(node_id, details)

                nodes_seen += 1
                if nodes_seen >= _MAX_TEST_NODES:
                    break

            # Needed for the subsequent edge validation
            self.set_nodes(set(nodes.keys()))

            edges_seen = 0
            if edges:
                for edge in edges.values():

                    # print(f"{str(edge)}", flush=True)
                    self.validate_edge(edge)

                    edges_seen += 1
                    if edges_seen >= _MAX_TEST_EDGES:
                        break

        return self.get_result()


def check_biolink_model_compliance_of_input_edge(
        edge: Dict[str, str],
        biolink_release=None
) -> Tuple[str, Optional[List[str]]]:
    """
    Validate an input edge object contents against the current BMT Biolink Model release.

    Sample method 'edge' with expected dictionary tags:

    {
        'subject_category': 'biolink:AnatomicalEntity',
        'object_category': 'biolink:AnatomicalEntity',
        'predicate': 'biolink:subclass_of',
        'subject': 'UBERON:0005453',
        'object': 'UBERON:0035769'
    }

    :param edge: basic contents of a templated input edge - S-P-O including concept Biolink Model categories
    :param biolink_release: Biolink Model (SemVer) version against which the edge object is to be validated

    :returns: 2-tuple of Biolink Model version (str) and List[str] (possibly empty) of error messages
    """
    validator = BiolinkValidator(graph_type=TrapiGraphType.Edge_Object, biolink_release=biolink_release)
    return validator.check_biolink_model_compliance_of_input_edge(edge)


def check_biolink_model_compliance_of_query_graph(
        graph: Dict,
        biolink_release=None
) -> Tuple[str, Optional[List[str]]]:
    """
    Validate a TRAPI-schema compliant Message Query Graph against the current BMT Biolink Model release.

    Since a Query graph is usually an incomplete knowledge graph specification,
    the validation undertaken is not 'strict'

    :param graph: query graph to be validated
    :param biolink_release: Biolink Model (SemVer) version against which the query graph is to be validated

    :returns: 2-tuple of Biolink Model version (str) and List[str] (possibly empty) of error messages
    """
    validator = BiolinkValidator(graph_type=TrapiGraphType.Query_Graph, biolink_release=biolink_release)
    return validator.check_biolink_model_compliance(graph)


def check_biolink_model_compliance_of_knowledge_graph(
        graph: Dict,
        biolink_release=None
) -> Tuple[str, Optional[List[str]]]:
    """
    Strict validation of a TRAPI-schema compliant Message Knowledge Graph against the active BMT Biolink Model release.

    :param graph: knowledge graph to be validated
    :param biolink_release: Biolink Model (SemVer) version against which the knowledge graph is to be validated

    :returns: 2-tuple of Biolink Model version (str) and List[str] (possibly empty) of error messages
    """
    validator = BiolinkValidator(graph_type=TrapiGraphType.Knowledge_Graph, biolink_release=biolink_release)
    return validator.check_biolink_model_compliance(graph)
