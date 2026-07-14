# GitHub - jtejido/ngac: Next Generation Access Control · GitHub

<!-- source: https://github.com/jtejido/ngac -->

This is a Golang port of NIST's reference core implementation, Policy Machine.
https://github.com/PM-Master/policy-machine-core
This port supports Neo4j as our Persistent Graph. In order to run it, it will require the APOC Core plugin to be installed. The config file is located here and this Cypher script can be ran to quickly serve the config's requirements.
https://pm-master.github.io/pm-master/policy-machine-core/
Be reminded that this is !!NOT FOR PROD!! as the APIs are still open for changes.
Obligation JSON Unmarshallers - file will be JSON (following the original's JSON schema).
Follow https://github.com/golang-standards/project-layout
DTO/DAO models for various Persistent and In-Memory graph DBs.
EPP to Publish/Subscribe model
