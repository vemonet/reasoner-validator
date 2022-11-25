import copy
from os.path import join, abspath, dirname
from typing import Optional, Any, Dict, List, Tuple

from yaml import load, BaseLoader

DEFAULT_CODES_DOCUMENTATION_FILE = abspath(join(dirname(__file__), "..", "docs", "validation_codes_dictionary.md"))


class CodeDictionary:

    CODE_DICTIONARY: str = abspath(join(dirname(__file__), "codes.yaml"))

    MESSAGE = "$message"
    DESCRIPTION = "$description"

    code_dictionary: Optional[Dict] = None

    @classmethod
    def _get_code_dictionary(cls) -> Dict:
        if not cls.code_dictionary:
            # Open the file and load the file
            with open(cls.CODE_DICTIONARY, mode='r') as f:
                cls.code_dictionary = load(f, Loader=BaseLoader)
        return cls.code_dictionary

    @classmethod
    def _get_nested_code_entry(
            cls,
            data: Dict[str, Dict],
            path: List[str],
            pos: int,
            facet: Optional[str],
            is_leaf: bool
    ) -> Optional[Dict[str, Any]]:
        """
        Navigate dot delimited tag 'path' into a multi-level dictionary, to return its associated value.

        :param data: Dict, multi-level data dictionary being traversed
        :param path: str, dotted JSON tag path
        :param pos: int, zero-based current position in tag path
        :param facet: Optional[str], constraint on code entry facet to be returned; if specified, should be either
                                     "message" or "description" (default: return all facets of the code entry)
        :param is_leaf: bool, only return entry if it is a 'leaf' of the code tree
        :return: Dict, value of the multi-level tag, if available; 'None' otherwise if no tag value found in the path
        """
        tag = path[pos]
        if tag not in data:
            return None

        pos += 1
        if pos == len(path):
            entry: Dict = data[tag]

            if not entry:
                # sanity check...
                return None

            # If the is_leaf flag is True, then the expected code value *must* be a
            # code subtree leaf which, at a minimum, must contain a MESSAGE template.
            # Conversely, a MESSAGE template should not be there if a code subtree is expected?
            if is_leaf and cls.MESSAGE not in entry or not is_leaf and cls.MESSAGE in entry:
                return None

            if facet:
                # need to filter on 'facet' here
                # TODO: this particular code is only good for leaves of the code tree?!??
                return {key: value for key, value in entry.items() if key == f"${facet.lower()}"}
            else:
                return copy.deepcopy(entry)
        else:
            return cls._get_nested_code_entry(data[tag], path, pos, facet, is_leaf)

    @classmethod
    def get_code_subtree(
            cls,
            code: str,
            facet: Optional[str] = None,
            is_leaf: Optional[bool] = False
    ) -> Optional[Tuple[str, Dict]]:
        """
        Get subtree of specified dot-delimited tag name, returned with message type (i.e. info, warning, error).
        If optional 'is_leaf' flag is set to True, then only return the code if it is a terminal leaf in the code tree.

        :param code: Optional[str], dot delimited validation message code identifier (None is ok, but returns None)
        :param facet: Optional[str], constraint on code entry facet to be returned; if specified, should be either
                                     "message" or "description" (default: return all facets of the code entry)
        :param is_leaf: Optional[bool], only return entry if it is a 'leaf' of the code tree (default: False)
        :return: Optional[Tuple[str, Dict[str,str]]], 2-tuple of the code type (i.e. info, warning, error) and the
                 validation message entry (dictionary); None if empty code or code unknown in the code dictionary,
                 or (if the is_leaf option is 'True') if the code doesn't resolve to a single leaf.
        """
        if not code:
            return None

        codes: Dict = cls._get_code_dictionary()
        code_path = code.split(".")
        value: Optional[Dict[str, str]] = cls._get_nested_code_entry(codes, code_path, 0, facet, is_leaf)
        if value is not None:
            return code_path[0], value
        else:
            return None

    @classmethod
    def get_code_entry(cls, code: Optional[str], facet: Optional[str] = None) -> Optional[Dict[str, str]]:
        """
        Get the single code entry corresponding to the given code, if available.

        :param code: Optional[str], dot delimited validation message code identifier (None is ok, but returns None)
        :param facet: Optional[str], constraint on code entry facet to be returned; if specified, should be either
                                     "message" or "description" (default: return all facets of the code entry)
        :return: Dict, single terminal leaf code entry (complete with indicated or all facets)
        """
        value: Optional[Tuple[str, Dict[str, str]]] = cls.get_code_subtree(code, facet=facet, is_leaf=True)
        if not value:
            return None
        entry: Optional[Dict[str, str]]
        message_type, entry = value
        return entry

    @classmethod
    def get_message_template(cls, code: Optional[str]) -> Optional[str]:
        entry: Optional[Dict[str, str]] = cls.get_code_entry(code)
        return entry[cls.MESSAGE] if entry else None

    @classmethod
    def get_description(cls, code: Optional[str]) -> Optional[str]:
        entry: Optional[Dict[str, str]] = cls.get_code_entry(code)
        return entry[cls.DESCRIPTION] if entry else None

    @classmethod
    def display(cls, **message):
        assert message and 'code' in message  # should be non-empty, containing a code
        code: str = message.pop('code')
        value: Optional[Tuple[str, Dict[str, str]]] = cls.get_code_subtree(code, is_leaf=True)
        assert value, f"CodeDictionary.display(): unknown message code {code}"
        message_type, entry = value
        code_parts: List[str] = [part.capitalize() for part in code.replace("_", ".").split(".")[1:-1]]
        context: str = ' '.join(code_parts) + ': ' if code_parts else ''
        template: str = entry[cls.MESSAGE]
        if message:
            # Message template parameterized with additional named parameter
            # message context, assumed to be referenced by the template
            return f"{message_type.upper()} - {context}{template.format(**message)}"
        else:
            # simple scalar message without parameterization?
            return f"{message_type.upper()} - {context}{template}"

    @classmethod
    def _dump_code_markdown_entries(cls, root: str, code_subtree: Dict, markdown_file):
        for tag, value in code_subtree.items():
            if isinstance(value, Dict):
                # Recurse down to leaf of tree
                cls._dump_code_markdown_entries(f"{root}.{tag}", value, markdown_file)
            elif isinstance(value, str):
                print(f"### {root}.{tag}\n\n{value}\n", file=markdown_file)
            #
            # Future design of the codes dictionary *might* provide
            # for additional descriptive contents in a list of strings
            #
            # elif isinstance(value, List):
            #     print(f"### {root}.{tag}\n\n{value}\n", file=markdown_file)
            #     for item in value:
            #         print(f"- {item}", file=markdown_file)
            else:
                raise RuntimeError("Unknown code data type?")

    @classmethod
    def markdown(cls, filename: str = DEFAULT_CODES_DOCUMENTATION_FILE) -> bool:
        """Dump the Code Dictionary into a validation_codes_dictionary.md Markdown file, for documentation purposes.

        :param filename: str, defaults to DEFAULT_CODES_DOCUMENTATION_FILE
        :return: bool, True if successful; False otherwise
        """
        code_dictionary: Dict = cls._get_code_dictionary()

        try:
            with open(filename, mode='w') as markdown_file:
                print("# Validation Codes Dictionary\n", file=markdown_file)
                top_level_tag: str
                for top_level_tag in code_dictionary.keys():
                    top_level_name = "Information" if top_level_tag == "info" else top_level_tag.capitalize()
                    print(f"## {top_level_name}\n", file=markdown_file)
                    cls._dump_code_markdown_entries(
                        top_level_tag,
                        code_dictionary[top_level_tag],
                        markdown_file=markdown_file
                    )

        except IOError:
            return False

        return True


if __name__ == '__main__':
    CodeDictionary.markdown()
