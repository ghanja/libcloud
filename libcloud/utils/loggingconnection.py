# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import absolute_import

try:
    import simplejson as json
except:
    import json

from pipes import quote as pquote
from xml.dom.minidom import parseString

import sys
import os

from libcloud.common.base import (LibcloudConnection,
                                  HTTPResponse)
from libcloud.utils.py3 import httplib
from libcloud.utils.py3 import PY3
from libcloud.utils.py3 import StringIO
from libcloud.utils.py3 import u
from libcloud.utils.py3 import b


from libcloud.utils.misc import lowercase_keys
from libcloud.utils.compression import decompress_data


class LoggingConnection(LibcloudConnection):
    """
    Debug class to log all HTTP(s) requests as they could be made
    with the curl command.

    :cvar log: file-like object that logs entries are written to.
    """

    protocol = 'https'
    port = None

    log = None
    http_proxy_used = False

    def _log_response(self, r):
        rv = "# -------- begin %d:%d response ----------\n" % (id(self), id(r))
        ht = ""
        v = r.version
        if r.version == 10:
            v = "HTTP/1.0"
        if r.version == 11:
            v = "HTTP/1.1"
        ht += "%s %s %s\r\n" % (v, r.status, r.reason)
        body = r.read()
        for h in r.getheaders():
            ht += "%s: %s\r\n" % (h[0].title(), h[1])
        ht += "\r\n"

        # this is evil. laugh with me. ha arharhrhahahaha
        class fakesock(object):
            def __init__(self, s):
                self.s = s

            def makefile(self, *args, **kwargs):
                if PY3:
                    from io import BytesIO
                    cls = BytesIO
                else:
                    cls = StringIO

                return cls(b(self.s))
        rr = r
        headers = lowercase_keys(dict(r.getheaders()))

        encoding = headers.get('content-encoding', None)
        content_type = headers.get('content-type', None)

        if encoding in ['zlib', 'deflate']:
            body = decompress_data('zlib', body)
        elif encoding in ['gzip', 'x-gzip']:
            body = decompress_data('gzip', body)

        pretty_print = os.environ.get('LIBCLOUD_DEBUG_PRETTY_PRINT_RESPONSE',
                                      False)

        if r.chunked:
            ht += "%x\r\n" % (len(body))
            ht += body.decode('utf-8')
            ht += "\r\n0\r\n"
        else:
            if pretty_print and content_type == 'application/json':
                try:
                    body = json.loads(body.decode('utf-8'))
                    body = json.dumps(body, sort_keys=True, indent=4)
                except:
                    # Invalid JSON or server is lying about content-type
                    pass
            elif pretty_print and content_type == 'text/xml':
                try:
                    elem = parseString(body.decode('utf-8'))
                    body = elem.toprettyxml()
                except Exception:
                    # Invalid XML
                    pass

            ht += u(body)

        if sys.version_info >= (2, 6) and sys.version_info < (2, 7):
            cls = HTTPResponse
        else:
            cls = httplib.HTTPResponse

        rr = cls(sock=fakesock(ht), method=r._method,
                 debuglevel=r.debuglevel)
        rr.begin()
        rv += ht
        rv += ("\n# -------- end %d:%d response ----------\n"
               % (id(self), id(r)))

        rr._original_data = body
        return (rr, rv)

    def _log_curl(self, method, url, body, headers):
        cmd = ["curl"]

        if self.http_proxy_used:
            if self.proxy_username and self.proxy_password:
                proxy_url = 'http://%s:%s@%s:%s' % (self.proxy_username,
                                                    self.proxy_password,
                                                    self.proxy_host,
                                                    self.proxy_port)
            else:
                proxy_url = 'http://%s:%s' % (self.proxy_host,
                                              self.proxy_port)
            proxy_url = pquote(proxy_url)
            cmd.extend(['--proxy', proxy_url])

        cmd.extend(['-i'])

        if method.lower() == 'head':
            # HEAD method need special handling
            cmd.extend(["--head"])
        else:
            cmd.extend(["-X", pquote(method)])

        for h in headers:
            cmd.extend(["-H", pquote("%s: %s" % (h, headers[h]))])

        cert_file = getattr(self, 'cert_file', None)

        if cert_file:
            cmd.extend(["--cert", pquote(cert_file)])

        # TODO: in python 2.6, body can be a file-like object.
        if body is not None and len(body) > 0:
            cmd.extend(["--data-binary", pquote(body)])

        cmd.extend(["--compress"])
        cmd.extend([pquote("%s://%s:%d%s" % (self.protocol, self.host,
                                             self.port, url))])
        return " ".join(cmd)

    def getresponse(self):
        r = LibcloudConnection.getresponse(self)
        if self.log is not None:
            r, rv = self._log_response(r)
            self.log.write(rv + "\n")
            self.log.flush()
        return r

    def request(self, method, url, body=None, headers=None):
        headers.update({'X-LC-Request-ID': str(id(self))})
        if self.log is not None:
            pre = "# -------- begin %d request ----------\n" % id(self)
            self.log.write(pre +
                           self._log_curl(method, url, body, headers) + "\n")
            self.log.flush()
        return LibcloudConnection.request(self, method, url, body,
                                          headers)
