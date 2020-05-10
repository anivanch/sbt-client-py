## sbt-client-py
Thin async client for sbt (scala build tool).

Main purpose of this client is for writing pre-commit
hooks, as starting a new sbt instance for each hook
leads to significantly increased execution time.
This client allows to start an sbt server once (which is done
automatically, if needed) and reuse it for running all subsequent hooks.

Inspired by https://github.com/cb372/sbt-client, which is written in rust
and forces a rust dependency for running hooks, which is not always convenient.

## Installation
To use as a library: \
`pip install sbt-client-py`

To use as a script: \
`git clone git@github.com:anivanch/sbt-client-py.git`

## Usage
### Using as library
This package mainly provides a single class `SbtClient` with
a two public methods: `connect` and `execute`. After creating
a client call `connect` to find an existing sbt server or
start a new one in case none were found. Then call `execute`
to run sbt commands. It's important to note that `execute`
will only run the first sbt command in the submitted line.

### Using as a python script
You can also run this package using python interpreter.
First command line argument will be passed to the client as
an sbt command. For example, the following line
starts a client and runs `clean`: \
`python -m sbt_client clean`

### Caveats
This client will refuse to work when its working directory
is not a valid sbt project (which is determined simply
by the presence of a `projct` folder and a `build.sbt` file).

## How it works
When invoked, a client checks whether or not a `project/target/active.json` file
exists (which is always created by the running sbt server and
deleted on the server shutdown). If not, it starts a new sbt
server for the project by simply running `sbt` command in a subprocess
and waits for the server to startup. When server is available,
the client connects by unix domain socket with uri taken from
`project/target/active.json` and sends the sbt command line
using json rpc api.
