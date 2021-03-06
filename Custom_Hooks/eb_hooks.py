# This file is part of JSC's public easybuild repository (https://github.com/easybuilders/jsc)
import os
import re
import subprocess

from easybuild.tools.run import run_cmd
from easybuild.tools.config import build_option
from easybuild.tools.config import install_path
from easybuild.tools.build_log import EasyBuildError, print_msg, print_warning
from easybuild.tools.toolchain.toolchain import SYSTEM_TOOLCHAIN_NAME
from easybuild.toolchains.compiler.systemcompiler import TC_CONSTANT_SYSTEM

SUPPORTED_COMPILERS = ["GCC", "iccifort", "intel-compilers", "NVHPC", "PGI"]
SUPPORTED_MPIS = ["impi", "psmpi", "OpenMPI", "BullMPI"]
# Maintain toplevel list for easy use of --try-toolchain
SUPPORTED_TOPLEVEL_TOOLCHAIN_FAMILIES = [
    "intel",
    "intel-para",
    "iomkl",
    "gpsmkl",
    "gomkl",
    "npsmkl",
    "nvomkl",
    "pmvmklc",
    "gmvmklc",
]
SUPPORTED_MPI_TOOLCHAIN_FAMILIES = [
    "iimpi",
    "ipsmpi",
    "iompi",
    "gpsmpi",
    "gompi",
    "npsmpic",
    "nvompic",
    "gmvapich2c",
    "pmvapich2c",
]
# Could potentially make a dictionary of names and supported versions here but that is
# probably overkill
SUPPORTED_TOOLCHAIN_FAMILIES = (
    SUPPORTED_COMPILERS
    + ["gcccoremkl"]
    + ["GCCcore"]
    + SUPPORTED_MPI_TOOLCHAIN_FAMILIES
    + SUPPORTED_TOPLEVEL_TOOLCHAIN_FAMILIES
)
VETOED_INSTALLATIONS = {
    'juwelsbooster': ['impi', 'impi-settings', 'BullMPI', 'BullMPI-settings'],
    'juwels': ['BullMPI', 'BullMPI-settings'],
    'jurecadc': [''],
    'jurecabooster': [
        'OpenMPI', 'OpenMPI-settings',
        'CUDA', 'nvidia-driver',
        'UCX', 'UCX-settings',
        'NCCL', 'NCCL-settings', 'NVHPC',
        'BullMPI', 'BullMPI-settings',
        'pscom'
    ],
    'jusuf': ['impi', 'impi-settings', 'BullMPI', 'BullMPI-settings'],
    'hdfml': ['BullMPI', 'BullMPI-settings'],
    'deep': ['BullMPI', 'BullMPI-settings'],
}

TWEAKABLE_DEPENDENCIES = {
    'UCX': 'default',
    'CUDA': '11.5',
    'Mesa': ('OpenGL', '2021b'),
    'libglvnd': ('OpenGL', '2021b'),
    'libxc': '5.1.7',
    'glu': ('OpenGL', '2021b'),
    'glew': ('OpenGL', '2021b'),
    'Boost': '1.78.0',
    'Boost.Python': '1.78.0',
}

SIDECOMPILERS = ['AOCC', 'Clang']

common_site_contact = 'Support <sc@fz-juelich.de>'

# Also maintain a list of CUDA enabled compilers
CUDA_ENABLED_TOOLCHAINS = ["pmvmklc", "gmvmklc", "gmvapich2c", "pmvapich2c"]
# Use this for a heuristic to see if the easyconfig comes from the Golden Repo
GOLDEN_REPO = "Golden_Repo"

# Some modules should use modaltsoftname by default
REQUIRE_MODALTSOFTNAME = {
    "impi": "IntelMPI",
    "psmpi": "ParaStationMPI",
    "iccifort": "Intel",
    "intel-compilers": "Intel",
}


def installation_vetoer(ec):
    "Check whether this package is NOT supposed to be installed in this system, and abort if necessary"
    name = ec['name']
    system_name = os.getenv('LMOD_SYSTEM_NAME')
    if system_name is None:
        with open('/etc/FZJ/systemname') as sn:
            system_name = sn.read()
    if name in VETOED_INSTALLATIONS[system_name]:
        print_warning(
            "\nYou are attempting to install software that should not be installed in this system.\n"
            "Please double check the list of packages that you are attempting to install. The following\n"
            f"packages can't be installed in {system_name}:\n"
        )
        for package in VETOED_INSTALLATIONS[system_name]:
            print_msg(f"- {package}", stderr=True)
        exit(1)


def get_user_info():
    # Query jutil to extract the contact information
    if os.getenv('CI') is None:
        jutil_path = os.getenv('JUMO_USRCMD_EXEC')
        if os.path.isfile(jutil_path) and os.access(jutil_path, os.X_OK):
            jutil = subprocess.Popen([jutil_path, 'person', 'show', '-o',
                                      'parsable'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            stdout, stderr = jutil.communicate()
            if not stderr:
                return stdout.decode('utf-8').splitlines()[-1].split('|')[0:2]
            else:
                print_warning(f'Could not query jutil: {stderr}')
                exit(1)
        else:
            name = os.getenv('SITE_CONTACT_NAME')
            email = os.getenv('SITE_CONTACT_EMAIL')
            if name and email:
                return [name, email]
            else:
                print_warning(
                    f"\n'jutil' is not present and 'SITE_CONTACT_NAME' or 'SITE_CONTACT_EMAIL' are not defined\n"
                    "Please defined both in your environment and try again\n"
                )
                exit(1)
    else:
        return ['CI user', 'ci_user@fz-juelich.de']


def format_site_contact(name, email, default_contact=True, alternative_contact=''):
    if default_contact:
        if alternative_contact:
            contact = alternative_contact
        else:
            contact = common_site_contact
        return contact+', software installed by '+name+' <'+email+'>'
    else:
        return 'Software installed by '+name+' <'+email+'>'


def inject_site_contact(ec, site_contacts):
    key = "site_contacts"
    value = site_contacts
    ec_dict = ec.asdict()

    if key in ec_dict:
        # Replace sc@fz-juelich.de with the first matched email in the provided contact
        email_found = None
        if ec_dict[key] is not None:
            # Check current values if it is a list
            if isinstance(ec_dict[key], list):
                for contact in ec_dict[key]:
                    email_found = re.search(
                        r'[\w\.-]+@[\w\.-]+', contact).group(0)
                    if email_found:
                        break
            # Check current values if it is a string
            else:
                email_found = re.search(
                    r'[\w\.-]+@[\w\.-]+', ec_dict[key]).group(0)

        if email_found:
            site_contacts = site_contacts.replace(
                'sc@fz-juelich.de', email_found, 1)
            ec.log.info("[parse hook] Injecting contact %s", value)
            ec[key] = site_contacts
        # Inject the default string
        else:
            ec.log.info("[parse hook] Injecting contact %s", value)
            ec[key] = value

    # Deprecated logic
    # if key in ec_dict:
    #     if ec_dict[key] is not None:
    #         # Check current values if it is a list
    #         if isinstance(ec_dict[key], list):
    #             for contact in ec_dict[key]:
    #                 email = re.search(r'[\w\.-]+@[\w\.-]+', site_contacts).group(0)
    #                 # Already in contact
    #                 if email in contact:
    #                     break
    #             # We looped to the end and did not find the contact in this list
    #             else:
    #                 # Do not add the generic one if there are other specific contacts
    #                 if 'sc@fz-juelich.de' not in site_contacts or len(ec_dict[key]) == 0:
    #                     ec.log.info("[parse hook] Injecting contact %s", value)
    #                     ec[key].append(site_contacts)
    #         # Check current values if it is a string
    #         else:
    #             email = re.search(r'[\w\.-]+@[\w\.-]+', site_contacts).group(0)
    #             # Do not add the generic one if there are other specific contacts
    #             if email not in ec_dict[key] and 'sc@fz-juelich.de' not in site_contacts:
    #                 ec.log.info("[parse hook] Injecting contact %s", value)
    #                 ec[key] = [ec_dict[key], site_contacts]
    #     else:
    #         ec.log.info("[parse hook] Injecting contact %s", value)
    #         ec[key] = value
    return ec


def parse_hook(ec, *args, **kwargs):
    """Custom parse hook to manage installations intended for JSC systems."""

    # First of all check if this should be installed
    if os.getenv('CI') is None:
        installation_vetoer(ec)

    # Process compiler options
    ec = inject_compiler_tweaks(ec)

    # Process MPI options
    ec = inject_mpi_tweaks(ec)

    # Process UCX options
    ec = inject_ucx_tweaks(ec)

    # Change module name if applicable
    ec = inject_modaltsoftname(ec)

    ec = inject_hidden_property(ec)

    ec = inject_gpu_property(ec)

    ec = inject_site_contact_and_user_labels(ec)

    if os.getenv('CI') is None:
        ec = tweak_dependencies(ec)

    ec = tweak_moduleclass(ec)

    # If we are parsing we are not searching, in this case if the easyconfig is
    # located in the search path, warn that it's dependencies will (most probably)
    # not be resolved
    if build_option("robot"):
        search_paths = build_option("search_paths") or []
        robot_paths = list(
            set(build_option("robot_path") + build_option("robot")))
        if ec.path:
            ec_dir_path = os.path.dirname(os.path.abspath(ec.path))
        else:
            ec_dir_path = ''
        if any(search_path in ec_dir_path for search_path in search_paths) and not any(
            robot_path in ec_dir_path for robot_path in robot_paths
        ):
            raise EasyBuildError(
                "\nYou are attempting to install an easyconfig distributed with "
                "EasyBuild but are not properly configured to resolve dependencies "
                "for this case. Please add additonal options:\n"
                "  eb --robot=$EASYBUILD_ROBOT:$EBROOTEASYBUILD/easybuild/easyconfigs --try-update-deps ...."
            )


def tweak_dependencies(ec):
    for dep_type in ["dependencies", "builddependencies"]:
        dependencies = ec[dep_type]
        # Check for dependencies to be tweaked. This assumes simply that the version is
        # being overwritten
        for dep_to_tweak in TWEAKABLE_DEPENDENCIES:
            for dep in dependencies:
                remove = False
                if dep_to_tweak == dep[0]:
                    list_dep = list(dep)
                    if isinstance(TWEAKABLE_DEPENDENCIES[dep_to_tweak], str):
                        list_dep[1] = TWEAKABLE_DEPENDENCIES[dep_to_tweak]
                    else:
                        # Assume that the name of the dependency also needs to be replaced, using the specified tuple
                        if TWEAKABLE_DEPENDENCIES[dep_to_tweak][0] not in [x[0] for x in dependencies]:
                            # The new dependency is not on the list, so add it
                            list_dep[0] = TWEAKABLE_DEPENDENCIES[dep_to_tweak][0]
                            list_dep[1] = TWEAKABLE_DEPENDENCIES[dep_to_tweak][1]
                        else:
                            # Remove it from the list to don't have the same dependency added N times
                            remove = True
                    if remove:
                        del dependencies[dependencies.index(dep)]
                    else:
                        dependencies[dependencies.index(dep)] = tuple(list_dep)
                        ec[dep_type] = dependencies

    return ec


def tweak_moduleclass(ec):
    if ec['name'] in SIDECOMPILERS:
        ec['moduleclass'] = 'sidecompiler'

    return ec


def inject_site_contact_and_user_labels(ec):
    ec_dict = ec.asdict()
    # Check where installations are going to go and add appropriate site contact
    # not sure of a fool-proof way to do this, let's just try a heuristic
    site_contacts = None
    # Non-user installation
    if install_path().lower().startswith('/p/software'):
        if 'swmanage' in os.getenv('USER'):
            site_contacts = common_site_contact
        else:
            installer_name, installer_email = get_user_info()
            site_contacts = format_site_contact(
                installer_name, installer_email)
        # Inject the user
        ec = inject_site_contact(ec, site_contacts)
    # User installation
    else:
        # Tag the build as a user build
        key = "modluafooter"
        value = 'add_property("build","user")'
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec_dict[key], value])
        else:
            ec[key] = value
        ec.log.info("[parse hook] Injecting user as Lmod build property")
        # Inject the user
        installer_name, installer_email = get_user_info()
        site_contacts = format_site_contact(
            installer_name, installer_email, default_contact=False)
        ec = inject_site_contact(ec, site_contacts)

    return ec


def inject_gpu_property(ec):
    ec_dict = ec.asdict()
    # Check if CUDA is in the dependencies, if so add the GPU Lmod tag
    if (
        "CUDA" in [dep[0] for dep in iter(ec_dict["dependencies"])]
        or ec_dict["toolchain"]["name"] in CUDA_ENABLED_TOOLCHAINS
    ):
        key = "modluafooter"
        value = 'add_property("arch","gpu")'
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec_dict[key], value])
        else:
            ec[key] = value
        ec.log.info("[parse hook] Injecting gpu as Lmod arch property")

    return ec


def inject_hidden_property(ec):
    ec_dict = ec.asdict()
    # Check if the module should be installed as hidden
    hidden_pkgs = os.getenv('EASYBUILD_HIDE_DEPS', '').split(',')
    if ec.name in hidden_pkgs:
        key = "hidden"
        if not key in ec_dict or ec_dict[key] is False:
            ec[key] = True
            ec.log.info(
                "[parse hook] Hiding software found in $EASYBUILD_HIDE_DEPS: %s",
                ec.name,
            )
    return ec


def inject_modaltsoftname(ec):
    ec_dict = ec.asdict()
    # Check if we need to use 'modaltsoftname'
    if ec.name in REQUIRE_MODALTSOFTNAME:
        key = "modaltsoftname"
        if not key in ec_dict or ec_dict[key] is None:
            ec[key] = REQUIRE_MODALTSOFTNAME[ec.name]
            ec.log.info(
                "[parse hook] Injecting modaltsoftname '%s' for '%s'",
                key,
                REQUIRE_MODALTSOFTNAME[ec.name],
            )
    return ec


def inject_ucx_tweaks(ec):
    # UCX require to load UCX-settings
    ec_dict = ec.asdict()
    if ec.name in 'UCX' and install_path().lower().startswith('/p/software'):
        key = "modluafooter"
        value = '''
if not ( isloaded("UCX-settings") ) then
    load("UCX-settings")
end
        '''
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec[key], value])
        else:
            ec[key] = value
        ec.log.info(
            "[parse hook] Injecting UCX-settings loading")

    return ec


def inject_mpi_tweaks(ec):
    ec_dict = ec.asdict()
    if ec.name == 'impi':
        ec['set_mpi_wrappers_all'] = 'True'
        ec.log.info("[parse hook] Injecting set_mpi_wrappers_all = True ")
    # MPIs are a family (in the Lmod sense) and require to load mpi-settings
    if ec.name in SUPPORTED_MPIS and install_path().lower().startswith('/p/software'):
        key = "modluafooter"
        value = '''
if not ( isloaded("mpi-settings") ) then
    load("mpi-settings")
end
family("mpi")
        '''
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec[key], value])
        else:
            ec[key] = value
        ec.log.info(
            "[parse hook] Injecting Lmod mpi family and mpi-settings loading")

    return ec


def inject_compiler_tweaks(ec):
    ec_dict = ec.asdict()
    # Compilers are are a family (in the Lmod sense)
    if ec.name in SUPPORTED_COMPILERS:
        key = "modluafooter"
        value = 'family("compiler")'
        if key in ec_dict:
            if not value in ec_dict[key]:
                ec[key] = "\n".join([ec[key], value])
        else:
            ec[key] = value
        ec.log.info("[parse hook] Injecting Lmod compiler family")
        # Supported compilers should also be recursively unloaded
        key = "recursive_module_unload"
        if not key in ec_dict or ec_dict[key] is None:
            ec[key] = True
            ec.log.info(
                "[parse hook] Injecting recursive module unloading for supported compiler"
            )

    return ec


def pre_ready_hook(self, *args, **kwargs):
    "When we are building something, do some checks for bad behaviour"
    ec = self.cfg

    # Grab name, path, toolchain, install path and check if we are installing
    # GCCcore/MPI
    name = ec["name"]
    path_to_ec = os.path.abspath(ec.path)
    toolchain = ec["toolchain"]
    is_gcccore = ec["name"] == "GCCcore"
    is_mpi = ec["moduleclass"] == "mpi" or name in SUPPORTED_MPIS

    # Don't let people use unsupported toolchains (by default)
    override_toolchain_check = os.getenv("JSC_OVERRIDE_TOOLCHAIN_CHECK")
    if not override_toolchain_check:
        toolchain_name = toolchain["name"]
        if not toolchain_name in SUPPORTED_TOOLCHAIN_FAMILIES and not install_path().lower().startswith('/p/software'):
            stage = os.getenv("STAGE", default=None)
            if stage:
                # Clean things up if it is a Devel stage
                stage = stage.replace("Devel-", "")
            else:
                stage = "<TOOLCHAIN_VERSION>"
            print_warning(
                "\nYou are attempting to install software with an unsupported "
                "toolchain (%s), please use additional arguments to map this to a supported"
                " toolchain:\n"
                " eb --try-toolchain=<SUPPORTED_TOOLCHAIN>,%s --try-update-deps ...\n"
                "where <SUPPORTED_TOOLCHAIN> comes from the list %s\n"
                "(if you really know what you are doing, you can override this "
                "behaviour by setting the %s environment variable)\n\n"
                "...exiting",
                toolchain_name,
                stage,
                SUPPORTED_TOPLEVEL_TOOLCHAIN_FAMILIES,
                "JSC_OVERRIDE_TOOLCHAIN_CHECK",
            )
            exit(1)

    # Don't let people install GCCcore since this probably won't work and will lead them
    # to reinstall most of our stack. Don't advertise that this can be overridden, only
    # experts should know that. This applies just to user installations
    override_gcccore_check = os.getenv("JSC_OVERRIDE_GCCCORE_CHECK")
    if not override_gcccore_check:
        if is_gcccore and not install_path().lower().startswith('/p/software'):
            print_warning(
                "\nYou are attempting to install GCCcore (%s) into a non-system "
                "location (%s), this won't work as expected without additional effort "
                "and is likely to lead to building a whole stack of dependencies even "
                "for simple software. Please contact sc@fz-juelich.de if you wish to "
                "discuss this further.\n\n"
                "...exiting",
                path_to_ec,
                install_path(),
            )
            exit(1)

    # Don't let people install a non-JSC MPI (and don't advertise that this can be
    # overridden, only experts should know that)
    override_mpi_check = os.getenv("JSC_OVERRIDE_MPI_CHECK")
    if not override_mpi_check:
        if is_mpi and GOLDEN_REPO not in path_to_ec and 'Overlays' not in path_to_ec \
                and os.getenv('USER') not in 'swmanage':
            print_warning(
                "\nYou are attempting to install a non-system MPI implementation (%s), "
                "this is very likely to lead to severe performance degradation. Please "
                "contact sc@fz-juelich.de if you wish to discuss this further.\n\n"
                "...exiting",
                path_to_ec,
            )
            exit(1)
