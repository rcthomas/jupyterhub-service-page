
import inspect
import logging
import os
import sys
from textwrap import dedent

from jinja2 import ChoiceLoader, FileSystemLoader, PrefixLoader

from jupyterhub.handlers.static import LogoHandler
from jupyterhub.log import CoroutineLogFormatter
from jupyterhub.utils import url_path_join
from jupyterhub._data import DATA_FILES_PATH

from tornado import ioloop, web
from tornado.log import app_log, access_log, gen_log

from traitlets import default, Bool, Dict, Instance, Integer, List, Unicode
from traitlets.config import Application

class Service(Application):

    flags = Dict({
        "generate-config": ({
            "Service": {
                "generate_config": True
            }},
            "Generate default config"
        )})

    config_file = Unicode(
        help=dedent("""
        Name of file used to configure service

        By default, the name of the configuration file is `{name}_config.py`,
        where `{name}` is the name of the service.  See documentation on the
        `name` parameter to see how it is determined by default.
        """)
    ).tag(config=True)

    @default("config_file")
    def default_config_file(self):
        return f"{self.name}_config.py"

    generate_config = Bool(
        False, 
        help=dedent("""
        Whether or not to produce default configuration file and exit

        If `True`, a default configuration script will be produced to standard
        output and the service then exits.  If `False` the service initializes
        and runs.
        """)
    ).tag(config=True)

    @default("log_level")
    def default_log_level(self):
        return logging.INFO

    @default("log_datefmt")
    def default_log_datefmt(self):
        """Exclude date from default date format"""
        return "%Y-%m-%d %H:%M:%S"

    @default("log_format")
    def default_log_format(self):
        """Override default log format to include time"""
        return "%(color)s[%(levelname)1.1s %(asctime)s.%(msecs).03d %(name)s %(module)s:%(lineno)d]%(end_color)s %(message)s"

    logo_file = Unicode(
        help=dedent("""
        Path to logo file

        By default, the logo file path is the path to the JupyterHub logo, but
        this can be changed to another logo file.
        """)
    ).tag(config=True)

    @default("logo_file")
    def default_logo_file(self):
        return os.path.join(DATA_FILES_PATH, "static/images/jupyterhub-80.png")

    name = Unicode(
        help=dedent("""
        Name of service

        By default, the name of a service is the same as its package name.
        """)
    ).tag(config=True)

    @default("name")
    def default_name(self):
        module_name = inspect.getmodule(self).__name__
        return module_name.split(".")[0]

    port = Integer(
        8888,
        help="Port that the service listens on"
    ).tag(config=True)

    service_prefix = Unicode(
        help=dedent("""
        Service URL prefix

        By default, this is `JUPYTERHUB_SERVICE_PREFIX/services/{name}` where
        `JUPYTERHUB_SERVICE_PREFIX` is an environment variable and `{name}` is
        the name of the service.  See documentation on the `name` parameter to
        see how it is determined by default.
        """)
    ).tag(config=True)

    @default("service_prefix")
    def default_service_prefix(self):
        return os.environ.get(
            "JUPYTERHUB_SERVICE_PREFIX",
            f"/services/{self.name}/"
        )

    static_path = Unicode(
        help=dedent("""
        Path to static assets like JS and CSS files

        By default, this is the same as what JupyterHub uses, and you probably
        should not change it unless you know what you are doing.
        """)
    ).tag(config=True)

    @default("static_path")
    def default_static_path(self):
        return os.path.join(DATA_FILES_PATH, "static")

    static_url_prefix = Unicode("",
        help=dedent("""
        Static URL prefix for assets like JS and CSS files

        By default, this is the same as what JupyterHub uses, and you probably
        should not change it unless you know what you are doing.
        """)
    ).tag(config=True)

    @default("static_url_prefix")
    def default_static_url_prefix(self):
        return url_path_join(self.service_prefix, "static/")

    template_paths = List(
        help=dedent("""
        Path to additional or specialized templates

        By default, the service uses the templates that JupyterHub uses and
        additional templates installed when the package is installed.  These 
        can be supplemented by additional templates using this parameter.
        """)
    ).tag(config=True)
    
    rules = List(
        help=dedent("""
        List of Tornado RequestHandler rule specifications

        By default, the service initializes with two Tornado RequestHandler
        rule specifications defined.  These handle static assets like JS, CSS,
        and logo files that JupyterHub's templates depend on.  These are stored
        on a parameter so that the user may manipulate or change them if they
        want to, after the service has been initialized and parameters are
        concretized, but before the service's Tornado application is started.
        """)
    )

    settings = Dict(
        help=dedent("""
        Settings to pass to Tornado web application

        By default, the service initializes with settings for `static_path` and
        `static_url_path` defined.  These are stored on a parameter so that the
        user may manipulate or change them if they want to, after the service
        has been initialized and parameters are concretized, but before the
        services' Tornado application is started.
        """)
    )

    webapp = Instance(
        web.Application,
        help="Tornado web application object for service"
    )

    def initialize(self, argv=None):
        """Initialize application but does not initialize Tornado app"""
        super().initialize(argv)
        self.handle_config()
        self.init_logging()
        self.init_rules()
        self.init_settings()
        self.init_loader()

    def handle_config(self):
        """Generate configuration file and exit, or read in if it exists"""
        if self.generate_config:
            print(self.generate_config_file())
            sys.exit()
        if self.config_file:
            self.load_config_file(self.config_file)

    def init_rules(self):
        """Initialize base Tornado web app rules"""
        self.rules = [
            self.static_file_handler_rule(),
            self.logo_handler_rule()
        ]

    def static_file_handler_rule(self):
        """Return static file handler Tornado web app rule"""
        return (
            self.service_prefix + r"static/(.*)",
            web.StaticFileHandler,
            {"path": self.static_path}
        )

    def logo_handler_rule(self):
        """Return logo handler Tornado web app rule"""
        return (
            self.service_prefix + r"logo",
            LogoHandler,
            {"path": self.logo_file}
        )

    def init_settings(self):
        """Initialize Tornado web app settings"""
        self.settings = {
            "static_path": self.static_path, 
            "static_url_prefix": self.static_url_prefix
        }

    def init_loader(self):
        """Initialize Template loader"""
        paths = self.base_template_paths()
        self.loader = ChoiceLoader([
            PrefixLoader({"templates": FileSystemLoader(paths[:1])}, "/"),
            FileSystemLoader(self.template_paths + paths)
        ])

    def base_template_paths(self):
        """Return paths for service and JupyterHub Jinja2 templates"""
        return [
            os.path.join(DATA_FILES_PATH, f"{self.name}/templates"),
            os.path.join(DATA_FILES_PATH, "templates")
        ]

    def init_webapp(self, rules=[]):
        """Initialize web app with service+JupyterHub rules and settings"""
        self.webapp = web.Application(rules + self.rules, **self.settings)

    _log_formatter_cls = CoroutineLogFormatter

    def init_logging(self): # Mostly copied from JupyterHub
        """Initialize logging to have JupyterHub conventions"""
        # This prevents double log messages because tornado use a root logger that
        # self.log is a child of. The logging module dipatches log messages to a log
        # and all of its ancenstors until propagate is set to False.
        self.log.propagate = False

        _formatter = self._log_formatter_cls(
            fmt=self.log_format, datefmt=self.log_datefmt
        )

        # hook up tornado 3's loggers to our app handlers
        for log in (app_log, access_log, gen_log):
            # ensure all log statements identify the application they come from
            log.name = self.log.name
        logger = logging.getLogger('tornado')
        logger.propagate = True
        logger.parent = self.log
        logger.setLevel(self.log.level)

    def start(self):
        """Commence being a service"""
        self.webapp.listen(self.port)
        ioloop.IOLoop.current().start()
