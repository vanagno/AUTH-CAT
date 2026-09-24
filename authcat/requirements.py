import importlib.metadata

# Named as pip installs them
modules_to_check = ['matplotlib', 'pandas', 'numpy', 'basemap','basemap-data-hires', 'cartopy', 'corner', 'emcee', 'scipy', 'reportlab', 'obspy']

# Packages imported under a different name from the one pip installs and data only packages
import_names = {'basemap': 'mpl_toolkits.basemap'}
data_packages = {'basemap-data-hires'}

def display_logo():
    logo = """
______________________________________________________________________________________________________
|      o       ooooo    ooo oooooooooooo oooo   oooo           .oooooo.        .o.      oooooooooooo | 
|     888       888      8  8    88    8  88     88           d8P'  `Y8b      .888.     8    88    8 | 
|    8 888      888      8       88       88     88          888             .8"888.         88      | 
|   8   888     888      8       88       88ooooo88          888            .8' `888.        88      | 
|  88ooo8888    888      8       88       88     88   8888   888           .88ooo8888.       88      | 
| 8       888    88     8        88       88     88          `88b    ooo  .8'     `888.      88      | 
|8         888     YbodP         88       88     88           `Y8bood8P'  88       8888      88      | 
|____________________________________________________________________________________________________|                                                                                                                                                                                                                                                                                                                                                                 
    """
    print(logo)

def check_modules(modules):
    for module in modules:
        try:
            if module in data_packages:
                importlib.metadata.version(module)
            else:
                __import__(import_names.get(module, module))
            print(f"{module} is installed.")
        except ImportError:  # includes importlib.metadata.PackageNotFoundError
            print(f"{module} is not installed.")

if __name__ == "__main__":
    display_logo()
    check_modules(modules_to_check)
