import re

try:
    from urllib.request import Request, urlopen, HTTPError  # Python3
except ImportError:
    from urllib2 import Request, urlopen, HTTPError  # Python2

from rdflib.namespace import RDF
from rdflib import Namespace

import xml.dom.minidom
import logging
logger = logging.getLogger(__name__)

try:
    from . import rdf
    from . import uniprot
except SystemError:
    import rdf
    import uniprot


def read_url(url):
    f = urlopen(url)
    content = f.read().decode('utf-8')
    f.close()
    try:
        f = urlopen(url)
        content = f.read().decode('utf-8')
        f.close()
    except IOError:
        #XXX: say something here
        content = None
    return content

def get_active_services():
    url = 'http://www.ebi.ac.uk/Tools/webservices/psicquic/registry/registry?action=ACTIVE&format=xml'
    content = read_url(url)
    dom = xml.dom.minidom.parseString(content)
    services = []
    for elem in dom.getElementsByTagName('service'):
        name = elem.getElementsByTagName('name')[0].firstChild.data
        restUrl = elem.getElementsByTagName('restUrl')[0].firstChild.data
        services.append((name, restUrl))
    return services

class PSICQUICRDFDataSource(rdf.RDFDataSourceBase):

    BIOPAX = Namespace("http://www.biopax.org/release/biopax-level3.owl#")

    ACTIVE_SERVICES = dict(get_active_services())

    def __init__(self, entity_id=None, cache=True, services=None):
        rdf.RDFDataSourceBase.__init__(self, None, cache)
        self.entity_id = entity_id

        if services is None:
            self.services = tuple(self.ACTIVE_SERVICES.keys())
        elif isinstance(services, str):
            if services in self.ACTIVE_SERVICES.keys():
                self.services = [services]
            else:
                self.services = []
        else:
            self.services = [
                name for name in services if name in self.ACTIVE_SERVICES.keys()]

    def count(self, service_name):
        if service_name not in self.ACTIVE_SERVICES.keys():
            return None  #XXX: Error?
        return int(read_url("{:s}interactor/{:s}?format=count".format(self.ACTIVE_SERVICES[service_name], self.entity_id)))

    def set_graph(self, service_name):
        if self.entity_id is None:
            return

        self.url = "{:s}interactor/{:s}?format=rdf-xml".format(self.ACTIVE_SERVICES[service_name], self.entity_id)

        if self.cache and self.url in self.GRAPH.keys():
            self.graph = self.fetch(self.url, self.cache)
            return

        cnt = self.count(service_name)
        # print(service_name, self.url, cnt)

        if cnt == 0:
            if self.cache:
                self.GRAPH[self.url] = None
            self.graph = None
        else:
            try:
                self.graph = self.fetch(self.url, self.cache)
            except HTTPError as e:
                if e.code in (500, 406, 400, 200):
                    if e.code == 500:
                        msg = "HTTP Error {:d}: Internal server error".format(e.code)
                    elif e.code == 406:
                        msg = "HTTP Error {:d}: Format not supported".format(e.code)
                    elif e.code == 400:
                        msg = "HTTP Error {:d}: Too many results for exporting in XML, Biopax and RDF".format(e.code)
                    elif e.code == 200:
                        msg = "HTTP Error {:d}: Not an error. Request is OK".format(e.code)
                    else:
                        msg = e.reason()
                    if self.cache:
                        self.GRAPH[self.url] = None
                    self.graph = None
                    # print(msg)
                else:
                    raise e

    def subjects(self, key):
        retval = []
        for name in self.services:
            self.set_graph(name)
            if self.graph is None:
                continue
            retval.extend(
                [str(sub) for sub in self.graph.subjects(RDF.type, self.BIOPAX[key])])
        return retval

    def proteins(self):
        return tuple(set(self.subjects("ProteinReference")))  #XXX: The return value includes entity_id itself.

    def small_molecules(self):
        return tuple(set(self.subjects("SmallMoleculeReference")))

    def interactors(self):
        return tuple(set(self.protein() + self.small_molecule()))

    def interactions(self):
        self.graph.query(
            """prefix biopax: <http://www.biopax.org/release/biopax-level3.owl#>
            search ?s where
            {{
            ?s
            rdf:type biopax:MolecularInteraction ;
            biopax:evidence ?o .
            ?o
            rdf:type biopax:Evidence ;

            }}
            """)
        return tuple(set(self.subjects("MolecularInteraction")))

def parse_psimitab_fields(column):
    if column is None or column == '-':
        return []

    # print(column)
    elem = r"(?P<{0}_quote>\")?(?P<{0}>(?({0}_quote)([^\"]|((?<=\\)\"))|([^()\"|\t:]|((?<=\\)\")))*)(?({0}_quote)\")"
    rexp = re.compile(r"({}\:{}(\({}\))?)([|]|$)".format(
        elem.format('xref'), elem.format('value'), elem.format('description')))

    keys = ('xref', 'value', 'description')
    start = 0
    retval = []
    for mobj in rexp.finditer(column):
        assert mobj.start() == start
        start = mobj.end()
        groupdict = mobj.groupdict()
        tmp = {}
        for key in keys:
            if groupdict[key] is not None:
                # tmp[key] = re.sub(r"(?<!\\)\\\"", '\"', groupdict[key])
                tmp[key] = re.sub(r"\\\"", '\"', groupdict[key])
            else:
                tmp[key] = None
        retval.append(tmp)
    return retval

def parse_psimitab(content, fmt='tab27'):
    """https://code.google.com/archive/p/psimi/wikis/PsimiTab27Format.wiki
    """
    columns = [
        'Unique identifier for interactor A', 'Unique identifier for interactor B',
        'Alternative identifier for interacor A', 'Alternative identifier for interactor B',
        'Aliases for A', 'Aliases for B',
        'Interaction detection methods',
        'First author', 'Identifier of the publication',
        'NCBI Taxonomy identifier for interactor A', 'NCBI Taxonomy identifier for interactor B',
        'Interaction types',
        'Source databases',
        'Interaction Identifier(s)',
        'Confidence score',
        'Complex expansion',
        'Biological role A', 'Biological role B',
        'Experimental role A', 'Experimental role B',
        'Interactor type A', 'Interactor type B',
        'Xref for interactor A', 'Xref for interactor B',
        'Xref for the interaction',
        'Annotaions for interactor A', 'Annotations for interactor B',
        'Annotations for the interaction',
        'NCBI Taxonomy identifier for the host organism',
        'Prameters of the interaction',
        'Creaction date', 'Update date',
        'Checksum for the interactor A', 'Checksum for the interactor B',
        'Checksum for the interaction',
        'negative',
        'Feature(s) for interactor A', 'Feature(s) for interactor B',
        'Stoichiometry for interactor A', 'Stoichiometroy for interactor B',
        'Participant identification method for interactor A',
        'Participant identification method for interactor B'
        ]
    if fmt == 'tab25':
        columns = columns[: 15]

    rexp = re.compile(r"(?P<fields>((\"([^\"]|((?<=\\)\"))*\")|([^\t\"])|((?<=\\)\"))+)(\t|$)")

    retval = []
    for line in content.split('\n'):
        line = line.strip()
        if line == '' or line[0] == '#':
            continue

        start = 0
        tmp = []
        for mobj in rexp.finditer(line):
            if mobj.start() != start:
                print(repr(line))
            assert mobj.start() == start
            start = mobj.end()
            tmp.append(mobj.group('fields'))
        assert len(tmp) == len(columns)
        retval.append(dict(zip(columns, tmp)))
    return retval

class PSICQUICPsimiTabDataSource(object):

    DATA = {}
    ACTIVE_SERVICES = dict(get_active_services())

    def __init__(self, entity=None, cache=True, services=None):
        self.fmt = 'tab25'
        self.entity_id = self.parse_entity(entity)
        self.cache = cache

        if services is None:
            self.services = tuple(self.ACTIVE_SERVICES.keys())
        elif isinstance(services, str):
            if services in self.ACTIVE_SERVICES.keys():
                self.services = [services]
            else:
                self.services = []
        else:
            self.services = [
                name for name in services if name in self.ACTIVE_SERVICES.keys()]

    @classmethod
    def parse_entity(cls, entity):
        return uniprot.UniProtDataSource.parse_entity(entity)

    def count(self, service_name):
        if service_name not in self.ACTIVE_SERVICES.keys():
            return None  #XXX: Error?
        return int(read_url("{:s}interactor/{:s}?format=count".format(self.ACTIVE_SERVICES[service_name], self.entity_id)))

    def set_data(self, service_name):
        if self.entity_id is None:
            return

        self.url = "{:s}interactor/{:s}?format={:s}".format(self.ACTIVE_SERVICES[service_name], self.entity_id, self.fmt)

        if self.cache and self.url in self.DATA.keys():
            self.data = self.fetch(self.url, self.cache)
            return

        cnt = self.count(service_name)
        logger.info("{} <{}> contains {} interactions.".format(service_name, self.url, cnt))

        if cnt == 0:
            if self.cache:
                self.DATA[self.url] = None
            self.data = None
        else:
            try:
                self.data = self.fetch(self.url, self.cache)
            except HTTPError as e:
                if e.code in (500, 406, 400, 200):
                    if e.code == 500:
                        msg = "HTTP Error {:d}: Internal server error".format(e.code)
                    elif e.code == 406:
                        msg = "HTTP Error {:d}: Format not supported".format(e.code)
                    elif e.code == 400:
                        msg = "HTTP Error {:d}: Too many results for exporting in XML, Biopax and RDF".format(e.code)
                    elif e.code == 200:
                        msg = "HTTP Error {:d}: Not an error. Request is OK".format(e.code)
                    else:
                        msg = e.reason()
                    if self.cache:
                        self.DATA[self.url] = None
                    self.data = None
                    logger.warning("{} returns {}.".format(service_name, msg))
                    # print(msg)
                else:
                    raise e

        if self.data is not None:
            logger.debug('{} provides {} interactions.'.format(service_name, len(self.data)))
        else:
            logger.debug('{} provides no interaction.')

    def fetch(self, url, cache=False):
        if not cache or url not in self.DATA.keys():
            data = parse_psimitab(read_url(url), self.fmt)
            # try:
            #     data = parse_psimitab(read_url(url), self.fmt)
            # except AssertionError as e:
            #     print('AssertionError')
            #     data = None
            if cache:
                self.DATA[url] = data
        else:
            data = self.DATA[url]
        return data

    def getiter(self):
        for name in self.services:
            self.set_data(name)
            if self.data is None:
                continue
            for data in self.data:
                yield data

    def getvalues(self, key):
        for data in self.getiter():
            if key in data.keys():
                yield data[key]

    def interactors(self):
        import ecell4

        retval = []
        for data in self.getiter():
            fields = [field['value'] for field in parse_psimitab_fields(data.get('Unique identifier for interactor A')) if field['xref'] == 'uniprotkb']
            if len(fields) != 1:
                fields = [field['value'] for field in parse_psimitab_fields(data.get('Alternative identifier for interacor A')) if field['xref'] == 'uniprotkb']
                if len(fields) != 1:
                    continue
            if fields[0] == self.entity_id:
                fields = [field['value'] for field in parse_psimitab_fields(data.get('Unique identifier for interactor B')) if field['xref'] == 'uniprotkb']
                if len(fields) != 1:
                    fields = [field['value'] for field in parse_psimitab_fields(data.get('Alternative identifier for interacor B')) if field['xref'] == 'uniprotkb']
                    if len(fields) != 1:
                        continue
            value = uniprot.UniProtDataSource.link(fields[0])
            retval.append(value)
        return tuple(set(retval))

    def interactions(self):
        return tuple([parse_psimitab_fields(value) for value in self.getvalues('Interaction Identifier(s)')])

# PSICQUICDataSource = PSICQUICRDFDataSource
PSICQUICDataSource = PSICQUICPsimiTabDataSource


if __name__ == "__main__":
    # print(get_active_services())

    services = None
    # services = "DIP"
    # services = "IntAct"
    # datasource = PSICQUICPsimiTabDataSource
    # datasource = PSICQUICRDFDataSource
    datasource = PSICQUICDataSource

    # res = datasource("P0AEZ3", services=services).proteins()
    # print(res, len(res))
    # res = datasource("P0AEZ3", services=services).small_molecules()
    # print(res, len(res))
    res = datasource("P0AEZ3", services=services).interactors()
    print(res, len(res))
    # res = datasource("P0AEZ3", services=services).interactions()
    # print(res, len(res))

    # print(parse_psimitab_column('psi-mi:"MI:0000"(a cv term)'))
    # print(parse_psimitab_column('psi-mi:"MI:0000"("I can now use braces ()()() or pipes ||| here and ::colons::")'))
    # print(parse_psimitab_column('uniprotkb:P12345(a \\"nice\\" protein)'))
    # print(parse_psimitab_column('uniprotkb:P12345("a \\"nice\\" protein")'))
    # print(parse_psimitab_column('psi-mi:"MI:0000"("I can now use braces ()()() or pipes ||| here and ::colons::")|psi-mi:"MI:0000"(a cv term)'))
    # print(parse_psimitab_column('psi-mi:ch10_ecoli(display_long)|uniprotkb:groS(gene name)|psi-mi:groS(display_short)|uniprotkb:groES(gene name synonym)|uniprotkb:mopB(gene name synonym)|uniprotkb:b4142(locus name)|uniprotkb:JW4102(locus name)|uniprotkb:Protein Cpn10(gene name synonym)|uniprotkb:GroES protein(gene name synonym)'))

    # print(parse_psimitab('psi-mi:"MI:0000"("I can now use tab \t here")\t-'))
    # print(parse_psimitab('dip:"DIP-35946N"\tdip:"DIP-35946N"\tuniprotkb:"P0AEZ3"\tuniprotkb:"P0AEZ3"\tDIP:"minD"("synonym")|DIP:"Septum site-determining protein minD"("synonym")\tDIP:"minD"("synonym")|DIP:"Septum site-determining protein minD"("synonym")\tpsi-mi:"MI:0018"("two hybrid")\t-\tpubmed:"17242352"(identity)|imex:"IM-22717-2"(imex-primary)\ttaxid:83333("Escherichia coli K12")\ttaxid:83333("Escherichia coli K12")\tpsi-mi:"MI:0915"("physical association")\tpsi-mi:"MI:0465"("DIP")\tdip:"DIP-196612E"\t-\t-\t-\t-\t-\t-\tpsi-mi:"MI:0326"("protein")\tpsi-mi:"MI:0326"("protein")\tentrez gene/locuslink:"945741"\tentrez gene/locuslink:"945741"\t-\t-\t-\t-\t\t-\t2016-07-31\t-\t-\t-\t-\t-\t-\t-\t-\t-\t-\t\t-'))
