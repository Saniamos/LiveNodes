from class_registry import ClassRegistry, EntryPointClassRegistry

class Register():
    def __init__(self):
        self.nodes = Entrypoint_Register(entrypoints='livenodes.nodes')
        # I don't think we need the registry for ports, as these are imported via the nodes classes anyway
        # self.ports = Entrypoint_Register(entrypoints='livenodes.ports')

    def package_enable(self, package_name):
        raise NotImplementedError()

    def package_disable(self, package_name):
        raise NotImplementedError()

# yes, this basically just wraps the ClassRegistry, but i am contemplating namespacing the local_registries
# and also allows to merge local registries or classes (currently only used in a test case, but the scenario of registering a class outside of a package is still valid)
class Entrypoint_Register():

    def __init__(self, entrypoints='livenodes.nodes'):
        # create local registry
        self.reg = ClassRegistry()
        
        # load all findable packages
        self.installed_packages = EntryPointClassRegistry(entrypoints)
        self.add_register(self.installed_packages)

    def add_register(self, register):
        for key, val in register.items():
            self.register(key=key.lower(), class_=val)

    def decorator(self, cls):
        self.register(key=cls.__name__.lower(), class_=cls)
        return cls

    def register(self, key, class_):
        return self.reg._register(key=key.lower(), class_=class_)

    def get(self, key, *args, **kwargs):
        return self.reg.get(key.lower(), *args, **kwargs)
