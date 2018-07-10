%if %defined scl
%scl_package cargo
%global scl_source set +ex; . scl_source enable %scl || exit $?; set -ex
%else
%global pkg_name cargo
%endif

# Only x86_64 and i686 are Tier 1 platforms at this time.
# https://forge.rust-lang.org/platform-support.html
#global rust_arches x86_64 i686 armv7hl aarch64 ppc64 ppc64le s390x
%global rust_arches x86_64 i686 aarch64 ppc64 ppc64le s390x

# Only the specified arches will use bootstrap binaries.
#global bootstrap_arches %%{rust_arches}

%if 0%{?rhel} && !0%{?epel}
%bcond_without bundled_libgit2
%else
%bcond_with bundled_libgit2
%endif

Name:           %{?scl_prefix}cargo
Version:        0.23.0
Release:        1%{?dist}
Summary:        Rust's package manager and build tool
License:        ASL 2.0 or MIT
URL:            https://crates.io/
ExclusiveArch:  %{rust_arches}

%global cargo_version %{version}
%global cargo_bootstrap 0.22.0

Source0:        https://github.com/rust-lang/%{pkg_name}/archive/%{cargo_version}/%{pkg_name}-%{cargo_version}.tar.gz

Patch1:         cargo-0.23.0-disable-mdbook.patch

# Get the Rust triple for any arch.
%{lua: function rust_triple(arch)
  local abi = "gnu"
  if arch == "armv7hl" then
    arch = "armv7"
    abi = "gnueabihf"
  elseif arch == "ppc64" then
    arch = "powerpc64"
  elseif arch == "ppc64le" then
    arch = "powerpc64le"
  end
  return arch.."-unknown-linux-"..abi
end}

%global rust_triple %{lua: print(rust_triple(rpm.expand("%{_target_cpu}")))}

%if %defined bootstrap_arches
# For each bootstrap arch, add an additional binary Source.
# Also define bootstrap_source just for the current target.
%{lua: do
  local bootstrap_arches = {}
  for arch in string.gmatch(rpm.expand("%{bootstrap_arches}"), "%S+") do
    table.insert(bootstrap_arches, arch)
  end
  local base = rpm.expand("https://static.rust-lang.org/dist/cargo-%{cargo_bootstrap}")
  local target_arch = rpm.expand("%{_target_cpu}")
  for i, arch in ipairs(bootstrap_arches) do
    i = i + 10
    print(string.format("Source%d: %s-%s.tar.xz\n",
                        i, base, rust_triple(arch)))
    if arch == target_arch then
      rpm.define("bootstrap_source "..i)
    end
  end
end}
%endif

# Use vendored crate dependencies so we can build offline.
# Created using https://github.com/alexcrichton/cargo-vendor/ 0.1.13
# It's so big because some of the -sys crates include the C library source they
# want to link to.  With our -devel buildreqs in place, they'll be used instead.
# FIXME: These should all eventually be packaged on their own!
Source100:      %{pkg_name}-%{version}-vendor.tar.xz

BuildRequires:  %{?scl_prefix}rust
BuildRequires:  make
BuildRequires:  cmake
BuildRequires:  gcc
BuildRequires:  git

%ifarch %{bootstrap_arches}
%global bootstrap_root cargo-%{cargo_bootstrap}-%{rust_triple}
%global local_cargo %{_builddir}/%{bootstrap_root}/cargo/bin/cargo
Provides:       bundled(%{pkg_name}-bootstrap) = %{cargo_bootstrap}
%else
BuildRequires:  %{name} >= 0.13.0
%global local_cargo %{_bindir}/%{pkg_name}
%endif

# Indirect dependencies for vendored -sys crates above
BuildRequires:  libcurl-devel
BuildRequires:  libssh2-devel
BuildRequires:  openssl-devel
BuildRequires:  zlib-devel
BuildRequires:  pkgconfig

%if %with bundled_libgit2
Provides:       bundled(libgit2) = 0.25.0
%else
BuildRequires:  libgit2-devel >= 0.24
%endif

# Cargo is not much use without Rust
Requires:       %{?scl_prefix}rust

%{?scl:Requires:%scl_runtime}

%description
Cargo is a tool that allows Rust projects to declare their various dependencies
and ensure that you'll always get a repeatable build.


%package doc
Summary:        Documentation for Cargo
BuildArch:      noarch

%description doc
This package includes HTML documentation for Cargo.


%prep

%ifarch %{bootstrap_arches}
%setup -q -n %{bootstrap_root} -T -b %{bootstrap_source}
test -f '%{local_cargo}'
%endif

# cargo sources
%setup -q -n %{pkg_name}-%{cargo_version}

# vendored crates
%setup -q -n %{pkg_name}-%{cargo_version} -T -D -a 100

%autopatch -p1

# define the offline registry
%global cargo_home $PWD/.cargo
mkdir -p %{cargo_home}
cat >.cargo/config <<EOF
[source.crates-io]
registry = 'https://github.com/rust-lang/crates.io-index'
replace-with = 'vendored-sources'

[source.vendored-sources]
directory = '$PWD/vendor'
EOF

# This should eventually migrate to distro policy
# Enable optimization, debuginfo, and link hardening.
%global rustflags -Copt-level=3 -Cdebuginfo=2 -Clink-arg=-Wl,-z,relro,-z,now

%build

%if %without bundled_libgit2
# convince libgit2-sys to use the distro libgit2
export LIBGIT2_SYS_USE_PKG_CONFIG=1
%endif

# use our offline registry and custom rustc flags
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"
%{?scl_source}

# cargo no longer uses a configure script, but we still want to use
# CFLAGS in case of the odd C file in vendored dependencies.
%{?__global_cflags:export CFLAGS="%{__global_cflags}"}
%{!?__global_cflags:%{?optflags:export CFLAGS="%{optflags}"}}
%{?__global_ldflags:export LDFLAGS="%{__global_ldflags}"}

%{local_cargo} build --release
sh src/ci/dox.sh


%install
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"
%{?scl_source}

%{local_cargo} install --root %{buildroot}%{_prefix}
rm %{buildroot}%{_prefix}/.crates.toml

mkdir -p %{buildroot}%{_mandir}/man1
%{__install} -p -m644 src/etc/man/cargo*.1 \
  -t %{buildroot}%{_mandir}/man1

%{__install} -p -m644 src/etc/cargo.bashcomp.sh \
  -D %{buildroot}%{_sysconfdir}/bash_completion.d/cargo

%{__install} -p -m644 src/etc/_cargo \
  -D %{buildroot}%{_datadir}/zsh/site-functions/_cargo

# Create the path for crate-devel packages
mkdir -p %{buildroot}%{_datadir}/cargo/registry

mkdir -p %{buildroot}%{_docdir}/cargo
cp -a target/doc %{buildroot}%{_docdir}/cargo/html


%check
export CARGO_HOME="%{cargo_home}"
export RUSTFLAGS="%{rustflags}"
%{?scl_source}

# some tests are known to fail exact output due to libgit2 differences
CFG_DISABLE_CROSS_TESTS=1 %{local_cargo} test --no-fail-fast || :


%files
%license LICENSE-APACHE LICENSE-MIT LICENSE-THIRD-PARTY
%doc README.md
%{_bindir}/cargo
%{_mandir}/man1/cargo*.1*
%{_sysconfdir}/bash_completion.d/cargo
%{_datadir}/zsh/site-functions/_cargo
%dir %{_datadir}/cargo
%dir %{_datadir}/cargo/registry

%files doc
%{_docdir}/cargo/html


%changelog
* Wed Dec 13 2017 Josh Stone <jistone@redhat.com> - 0.23.0-1
- Update to 0.23.0.

* Tue Dec 12 2017 Josh Stone <jistone@redhat.com> - 0.22.0-1
- Update to 0.22.0.

* Mon Sep 11 2017 Josh Stone <jistone@redhat.com> - 0.21.1-1
- Update to 0.21.1.

* Wed Sep 06 2017 Josh Stone <jistone@redhat.com> - 0.21.0-1
- Update to 0.21.0.

* Mon Jul 24 2017 Josh Stone <jistone@redhat.com> - 0.20.0-1
- Update to 0.20.0.
- Add a cargo-doc subpackage.

* Mon Jun 19 2017 Josh Stone <jistone@redhat.com> - 0.19.0-2
- Use the scl for install and check.

* Wed Jun 14 2017 Josh Stone <jistone@redhat.com> - 0.19.0-1
- Update to 0.19.0.

* Fri Jun 02 2017 Josh Stone <jistone@redhat.com> - 0.18.0-2
- Rebuild without bootstrap binaries.

* Fri Jun 02 2017 Josh Stone <jistone@redhat.com> - 0.18.0-1
- Bootstrap with the new SCL name.
