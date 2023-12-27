import xml.etree.ElementTree as ET
from typing import Optional, List
from enum import Enum
from geopy.distance import great_circle
import argparse


# Enum of types of sign that should be considered
class SignType(Enum):
    NONE = 0
    STOP = 1
    YIELD = 2


# These are the road types that should be considered for stop signs
ROAD_TYPES = [
    'motorway',
    'motorway_link',
    'trunk',
    'trunk_link',
    'primary',
    'primary_link',
    'secondary',
    'secondary_link',
    'tertiary',
    'tertiary_link',
    'unclassified',
    'residential',
    'living_street',
    'service'
]


class StopSignFixer:
    input_file: Optional[str] = None
    output_file: Optional[str] = None

    tree: Optional[ET.ElementTree] = None

    allway_stop_count = 0  # Number of all-way stop signs added
    direction_on_oneway_count = 0  # Number of direction=forward/backward tags added to one-way roads
    direction_near_intersection_count = 0  # Number of direction=forward/backward tags added near intersections

    skipped_count = 0  # Number of stop signs skipped because can't determine direction

    # Distance threshold for determining if a stop sign is near an intersection
    INTERSECTION_THRESHOLD = 50  # meters

    def __init__(self, input_file: str, output_file: str):
        self.input_file = input_file
        self.output_file = output_file

    def load(self):
        try:
            tree = ET.parse(self.input_file)
        except IOError:
            print("Error reading file")
            return
        self.tree = tree

    # Get all parent ways of a node
    def find_parent_ways(self, node_id: int) -> list[ET.Element]:
        if self.tree is None:
            raise Exception("No tree loaded")

        parent_ways = self.tree.findall(f'way/nd[@ref="{node_id}"]/..')
        return parent_ways

    @staticmethod
    def filter_parent_ways(ways: list[ET.Element]) -> list[ET.Element]:
        filtered_ways = []
        for way in ways:
            for tag in way.findall('tag'):
                if tag.attrib['k'] == 'highway' and tag.attrib['v'] in ROAD_TYPES:
                    filtered_ways.append(way)
                    break
        return filtered_ways

    @staticmethod
    def mark_as_all_way_stop(node: ET.Element) -> None:
        node.attrib['action'] = 'modify'
        stop_tag = ET.SubElement(node, 'tag')
        stop_tag.attrib['k'] = 'stop'
        stop_tag.attrib['v'] = 'all'
        node.insert(0, stop_tag)

    @staticmethod
    def print_sign_type(sign_type: SignType) -> str:
        if sign_type == SignType.STOP:
            return "stop"
        elif sign_type == SignType.YIELD:
            return "yield"
        else:
            return "none"

    # Process a single stop or yield sign
    def process_sign(self, node_id: int, sign_type: SignType) -> None:
        if self.tree is None:
            raise Exception("No tree loaded")

        # Find <way> with <nd> with ref containing node id
        ways = self.find_parent_ways(node_id)
        # If there are no parent ways, stop sign is disconnected from rest of map
        # This is probably an error
        if len(ways) == 0:
            self.skipped_count += 1
            print(f"Warning: node {node_id} has no parent ways")
            return
        filtered_ways = self.filter_parent_ways(ways)

        # Count # of parent ways with highway tag
        highway_count = 0
        for way in filtered_ways:
            has_highway_tag = False
            for tag in way.findall('tag'):
                if tag.attrib['k'] == 'highway' and tag.attrib['v'] in ROAD_TYPES:
                    has_highway_tag = True
                    break
            if has_highway_tag:
                highway_count += 1

        # If highway_count == 0, stop sign is not on a road
        # Might be on a footway or cycleway - we don't care about these
        if highway_count == 0:
            self.skipped_count += 1
            print(f"Warning: node {node_id} is not on a road")
            return
        # For stop sign only:
        # If highway_count >= 2, mark as all-way stop
        if sign_type == SignType.STOP and highway_count >= 2:
            # If highway_count == 2 we may be on a road which is
            # split into two ways.
            # Check if name is the same for both ways
            # If so we will generate a warning
            if highway_count == 2:
                name_same = False
                for way in filtered_ways:
                    name = None
                    for tag in way.findall('tag'):
                        if tag.attrib['k'] == 'name':
                            name = tag.attrib['v']
                            break
                    if name is not None:
                        for way2 in filtered_ways:
                            if way2 == way:
                                continue
                            name2 = None
                            for tag in way2.findall('tag'):
                                if tag.attrib['k'] == 'name':
                                    name2 = tag.attrib['v']
                                    break
                            if name2 is not None and name == name2:
                                name_same = True
                if name_same:
                    self.skipped_count += 1
                    print(f"Warning: node {node_id} is on a road split into two ways with the same name")
                    return
            node = self.tree.find(f'node[@id="{node_id}"]')
            self.mark_as_all_way_stop(node)
            self.allway_stop_count += 1
            print(f"Marked node {node_id} as all-way stop")
        # If highway_count == 1, we are on a road where we probably want to add
        # direction=forward and direction=backward to the stop or yield sign.
        if highway_count == 1:
            print(f"Processing node {node_id} with {self.print_sign_type(sign_type)} sign")
            way = ways[0]  # Get parent way
            # If we are at the end of the way
            # We do not want to add direction=forward or direction=backward
            # because there is no road after the sign
            ways_nodes: List[int] = []
            for nd in way.findall('nd'):
                ways_nodes.append(int(nd.attrib['ref']))
            index = ways_nodes.index(node_id)
            if index == 0 or index == len(ways_nodes) - 1:
                print(f"Warning: node {node_id} is at the end of a way")
                return

            # Check if road is one-way
            # If so we will always want to add direction=forward
            # (or direction=backward if the road is oneway=-1)
            oneway = 0
            for tag in way.findall('tag'):
                if tag.attrib['k'] == 'oneway':
                    if tag.attrib['v'] == 'yes':
                        oneway = 1
                    elif tag.attrib['v'] == '-1':
                        oneway = -1
            if oneway != 0:
                node = self.tree.find(f'node[@id="{node_id}"]')
                node.attrib['action'] = 'modify'
                direction_tag = ET.SubElement(node, 'tag')
                direction_tag.attrib['k'] = 'direction'
                if oneway == 1:
                    tag = 'forward'
                else:
                    tag = 'backward'
                direction_tag.attrib['v'] = tag
                self.direction_on_oneway_count += 1
                print(f"Added direction={tag} to node {node_id}")
                return
            node = self.tree.find(f'node[@id="{node_id}"]')
            # Get latitude and longitude of sign
            lat = float(node.attrib['lat'])
            lon = float(node.attrib['lon'])
            sign_lat_lon = (lat, lon)
            # If road is not one-way, we want to check distance to see
            # how far we are from the nearest intersection
            # If we are close to an intersection, we will want to add
            # direction=forward or direction=backward
            min_distance: Optional[int] = None
            closest_node_id: Optional[int] = None
            # Check to see if any roads are connected to that way
            for way_node_id in ways_nodes:
                # If node is the node with the sign, skip it
                if way_node_id == node_id:
                    continue
                # Get all roads connected to this node
                connected_ways = self.find_parent_ways(way_node_id)
                connected_ways = self.filter_parent_ways(connected_ways)
                # If there are no connected ways, skip this node
                if len(connected_ways) == 0:
                    continue
                # Get lat and lon of intersection
                lat = float(self.tree.find(f'node[@id="{way_node_id}"]').attrib['lat'])
                lon = float(self.tree.find(f'node[@id="{way_node_id}"]').attrib['lon'])
                intersection_lat_lon = (lat, lon)
                # Calculate distance between sign and intersection
                distance = great_circle(sign_lat_lon, intersection_lat_lon).meters
                if min_distance is None or distance < min_distance:
                    min_distance = distance
                    closest_node_id = way_node_id
            # If min_distance is None, there are no intersections nearby
            # If min_distance is not None, there is an intersection nearby
            # If min_distance is less than INTERSECTION_THRESHOLD, we want to add
            # direction=forward or direction=backward
            if min_distance is not None and min_distance < self.INTERSECTION_THRESHOLD:
                # Check if closest node_id is before or after node_id in parent way
                # If so, we want to add direction=forward
                # If not, we want to add direction=backward
                # Get index of node_id in parent way
                index = ways_nodes.index(node_id)
                # Get index of closest_node_id in parent way
                closest_index = ways_nodes.index(closest_node_id)
                if closest_index > index:
                    direction = 'forward'
                else:
                    direction = 'backward'
                node.attrib['action'] = 'modify'
                direction_tag = ET.SubElement(node, 'tag')
                direction_tag.attrib['k'] = 'direction'
                direction_tag.attrib['v'] = direction
                print(f"Added direction={direction} to node {node_id}")
                self.direction_near_intersection_count += 1
            else:
                print(f"Warning: node {node_id} is not near an intersection")

    def process(self):
        if self.tree is None:
            raise Exception("No tree loaded")

        for node in self.tree.findall('node'):
            sign_type = SignType.NONE
            already_fixed = False
            for tag in node.findall('tag'):
                if tag.attrib['k'] == 'highway' and tag.attrib['v'] == 'stop':
                    sign_type = SignType.STOP
                elif tag.attrib['k'] == 'highway' and tag.attrib['v'] == 'give_way':
                    sign_type = SignType.YIELD
                if tag.attrib['k'] == 'stop' and tag.attrib['v'] == 'all':
                    already_fixed = True
                    break
                if tag.attrib['k'] == 'direction':
                    already_fixed = True
                    break
            if already_fixed:
                continue
            if sign_type != SignType.NONE:
                node_id = int(node.attrib['id'])
                print(f"Found {self.print_sign_type(sign_type)} sign at node {node_id}")
                self.process_sign(node_id, sign_type)

        print(f"Added {self.allway_stop_count} all-way stop signs")
        print(f"Added {self.direction_on_oneway_count} direction=forward/backward tags to one-way roads")
        print(f"Added {self.direction_near_intersection_count} direction=forward/backward tags near intersections")
        print(f"Skipped {self.skipped_count} stop signs")

    def save(self):
        if self.tree is None:
            raise Exception("No tree loaded")
        self.tree.write(self.output_file, encoding='utf-8', xml_declaration=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Fix stop and yield signs')
    parser.add_argument('input_file', type=str, help='input file')
    parser.add_argument('output_file', type=str, help='output file')
    args = parser.parse_args()
    fixer = StopSignFixer(args.input_file, args.output_file)
    fixer.load()
    fixer.process()
    fixer.save()
