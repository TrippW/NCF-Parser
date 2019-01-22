"""This file is intended to parse an NCF into its components"""
import os

def trim(data):
    """removes spaces from a list"""
    ret_data = []
    for item in data:
        ret_data += item.replace(' ', '')
    return ret_data

class NCFParser:
    """parses NCF files into usable data"""

    # pylint: disable=too-many-instance-attributes
    # These are all reasonable instance attributes to initialize
    def __init__(self, starting_file=None):
        """Set up all needed parameters"""
        self.loaded = False
        self.parsed = False
        self.frames = {}
        self.nodes = {}
        self.signals = {}
        self.attributes = {}
        self.all_text = None
        self.current_file = starting_file
        if starting_file:
            self.set_file(starting_file)

#utility

    def _reset_data(self):
        """When setting a new file, clear all data"""
        self.loaded = False
        self.parsed = False
        self.frames = {}
        self.nodes = {}
        self.signals = {}

    def set_file(self, file_name):
        """takes a path to an NCF file, then reads and parses it"""
        if str(file_name[-3:]).lower() == 'ncf':
            if os.path.exists(file_name):
                self.current_file = file_name
                self._reset_data()
                self._read_file()
            else:
                raise FileNotFoundError(file_name+" doesn't exist")
        else:
            raise ValueError('Incorrect file type')

    def _read_file(self):
        """reads the text from the NCF file"""
        self.loaded = False
        with open(self.current_file) as file:
            self.all_text = file.read()
        self.loaded = True
        self._parse_file()


    def _find_ends(self, term, text=None):
        """utility function to find the brackets for a term in text"""
        if not text:
            text = self.all_text
        #add len of term since we know what we asked for and add 1 for the space
        start = text.find(term+' {')+len(term)+1
        if start == len(term):
            start = text.find(term+'{')+len(term)
        if start == len(term)-1:
            raise Exception('Term not found')
        end = temp = start
        while text[start:end].count('{') > text[start:end].count('}') or start == end:
            temp = end+1
            end = text.find('}', temp)+1
            if(end == 0) or (end == len(text)):
                break
        return (start+1, end-1)

    def _find_single_line_value(self, search_term, text=None):
        """find the data on a known signal line term"""
        if not text:
            text = self.all_text[::]
        return text[text.find(search_term):].split(';')[0].split('=')[-1].replace(' ', '')

#parsing/data collection

    def _parse_file(self):
        """parses the text from the NCF into nodes, signals, frames, and attributes"""
        text = self.all_text[::]
        while 'node ' in text:
            #find the node name
            node_name_start = text.find('node ')
            node_name_end = text.find(' {', node_name_start)
            search_term = text[node_name_start:node_name_end]
            name = search_term.split(' ')[1]
            #find the node text
            node_start, node_end = self._find_ends(search_term, text)
            node_text = text[node_start:node_end]
            #update the search text to look after the current node
            text = text[node_end+1:]
            #find the frame text and parse it
            frame_text_pos = self._find_ends('frames', node_text)
            self.nodes[name] = {}
            self.nodes[name]['frames'] = self._parse_all_frames(*frame_text_pos, node_text)
            #search node for specific values
            terms = ['NAD', 'LIN_protocol', 'bitrate']
            for term in terms:
                self.nodes[name][term] = self._find_single_line_value(term, node_text)

        self.parsed = True
        del self.all_text

    def _parse_all_frames(self, start, end, text):
        """initiates the parsing of all frames"""
        frame_text = text[start:end]
        pub_end = -1
        sub_end = -1
        self.frames['publish'] = {}
        self.frames['subscribe'] = {}
        #we run forever until we have processed all published and subscribed frames
        while True:
            pub_start = frame_text.find('publish ', pub_end+1)
            sub_start = frame_text.find('subscribe ', sub_end+1)
            #check if there is a publish frame to process
            if pub_start != -1:
                #process the publish frame
                pub_name = frame_text[pub_start:].split(' ')[1]
                pub_start, pub_end = self._find_ends('publish '+pub_name, frame_text[pub_end+1:])
                data = frame_text[pub_start:pub_end]
                self.frames['publish'][pub_name] = self._parse_frame(data)

            #check if there is a subscribe frame left to process
            if sub_start != -1:
                #process it if there are any
                sub_name = frame_text[sub_start:].split(' ')[1]
                sub_start, sub_end = self._find_ends('subscribe '+sub_name, frame_text[sub_end+1:])
                data = frame_text[sub_start:sub_end]
                self.frames['subscribe'][sub_name] = self._parse_frame(data)

            #if there are no publish or subscribe frames, we are don parsing and can break
            if (pub_start == -1) and (sub_start == -1):
                break
        return self.frames


    def _parse_frame(self, frame):
        """parses frames into name, id, publisher, length, and composing signals with offsets"""
        raw = {}
        raw['ID'] = frame[frame.find('message_ID'):].split(';')[0].split('=')[1].replace(' ', '')
        raw['len'] = frame[frame.find('length'):].split(';')[0].split('=')[1].replace(' ', '')
        raw['signals'] = {}
        signal_start, signal_end = self._find_ends('signals', frame)
        #add 1 to start to ignore the opening {
        signals = frame[signal_start:signal_end]
        while '{' in signals:
            signal_name = signals[:signals.find('{', 1)]
            signal_name = signal_name.replace(' ', '').replace('\n', '').replace('\t', '')
            raw[signal_name] = {}
            signal_data = signals[slice(*self._find_ends(signal_name, signals))]
            raw[signal_name]['encoding'] = self._parse_encoding(signal_data)
            signal_data = signal_data[:signal_data.find('encoding ')]
            signal_data = signal_data.replace('\n', '').replace('\t', '').replace(' ', '')
            for data in signal_data.split(';')[:3]:
                name, value = data.split('=')[:2]
                raw[signal_name][name] = value
            signals = signals[signals.find('}', signals.find('}')+1)+1:]
            self.signals[signal_name] = raw[signal_name]

        return raw

    # pylint: disable=no-self-use
    # This is still part of the overall class
    def _parse_encoding(self, encoding):
        """
        parses the encoded values for the signal. Shows the message if a logical value or the
        min, max, and init if a physical value
        """
        raw = {}
        encoding = encoding[encoding.find('{'):]
        encoding = encoding.replace('\t', '').replace('\n', '').replace('}', '').replace('{', '')
        _type = encoding.split(',')[0].split('_')[0]
        raw['type'] = _type
        encodings = encoding.split(';')
        if raw['type'].lower() == 'logical':
            for data in encodings:
                if data:
                    value, msg = data.split(',')[1:3]
                    raw[int(value)] = msg.replace('"', '')
        elif raw['type'].lower() == 'physical':
            data = encodings[0].split(',')
            raw['min'] = data[1].replace(' ', '')
            raw['max'] = data[2].replace(' ', '')
            raw['init'] = data[4].replace(' ', '')
        else:
            return None
        return raw

#data retrieval

    def get_nodes(self):
        """return all nodes"""
        return self.nodes

    def get_signals(self):
        """return all signals"""
        return self.signals

    def get_signals_by_publish_node(self, node):
        """return all signals for a given node"""
        data = {}
        for key, val in self.signals:
            if val['publisher'] == node:
                data[key] = val
        return data

    def get_frames(self):
        """return all frames"""
        return self.frames

    def get_frames_by_publish_node(self, node):
        """return all frames for a given publisher node"""
        data = {}
        for key, val in self.frames:
            if val['publisher'] == node:
                data[key] = val
        return data


    def get_all(self):
        """return all parsed data"""
        data = {
            'nodes' : self.nodes,
            'frames' : self.frames,
            'signals' : self.signals}
        return data
