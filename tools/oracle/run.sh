#!/usr/bin/env bash
# Regenerate the Scythebill oracle fixtures (tests/fixtures/oracle) after a taxonomy update.
#
#   tools/oracle/run.sh [scythebill checkout] [work dir]
#
# Builds Scythebill's model module from a scratch copy of the checkout (the checkout itself
# is never modified, and the copy leaves out .git, the taxonomy archive and any .bsxm), runs
# Oracle.java against the bundled taxonomies, and summarizes the output into fixtures.
#
# Needs: a Java 17+ runtime with the jdk.compiler module, and network access the first time
# (Maven and Scythebill's dependencies are downloaded into the work dir, not ~/.m2).
set -euo pipefail
cd "$(dirname "$0")/../.."

SCYTHEBILL="${1:-$HOME/Projects/scythebill-birdlist}"
WORK="${2:-${TMPDIR:-/tmp}/pipit-oracle}"
MAVEN_VERSION=3.9.11
PY=.venv/bin/python
mkdir -p "$WORK/bin"

if [[ ! -x "$WORK/apache-maven-$MAVEN_VERSION/bin/mvn" ]]; then
    base="https://archive.apache.org/dist/maven/maven-3/$MAVEN_VERSION/binaries"
    curl -fsSL "$base/apache-maven-$MAVEN_VERSION-bin.tar.gz" -o "$WORK/maven.tgz"
    curl -fsSL "$base/apache-maven-$MAVEN_VERSION-bin.tar.gz.sha512" -o "$WORK/maven.sha512"
    (cd "$WORK" && echo "$(cut -d' ' -f1 maven.sha512)  maven.tgz" | sha512sum -c - && tar xzf maven.tgz)
fi

# A javac stand-in for JDK runtimes without the launcher binary (-J options go to the JVM).
cat > "$WORK/bin/javac" <<'EOF'
#!/bin/bash
jvm=(); args=()
for a in "$@"; do case "$a" in -J*) jvm+=("${a#-J}");; *) args+=("$a");; esac; done
exec java --add-modules ALL-SYSTEM "${jvm[@]}" -m jdk.compiler/com.sun.tools.javac.Main "${args[@]}"
EOF
chmod +x "$WORK/bin/javac"

rsync -a --delete --exclude taxonomy --exclude mobile --exclude www --exclude packaging \
    --exclude .git --exclude '*.bsxm' "$SCYTHEBILL/" "$WORK/src/"
# Runtime-only JDKs lack ct.sym (needed by --release) and newer javac warns more (-Werror).
sed -i -e 's#<release>[0-9]*</release>#<source>17</source><target>17</target>#' \
    -e 's#<arg>-Werror</arg>##' "$WORK/src/pom.xml"

export PATH="$WORK/bin:$PATH"
export JAVA_HOME="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}"
(cd "$WORK/src" && "$WORK/apache-maven-$MAVEN_VERSION/bin/mvn" -B -q \
    -Dmaven.repo.local="$WORK/m2" -pl model -am -DskipTests \
    compile dependency:build-classpath -Dmdep.outputFile="$WORK/cp.txt")
CLASSPATH="$(cat "$WORK/cp.txt"):$WORK/src/model/target/classes"

FIXTURES=tests/fixtures/oracle
"$PY" -m pipit.packbuild.cli --scythebill "$SCYTHEBILL" --out "$WORK/pack" >/dev/null
PACK="$(ls "$WORK"/pack/pipit-pack-*.sqlite)"
"$PY" -I tools/oracle/make_corpus.py "$SCYTHEBILL" "$FIXTURES/corpus.txt"
FILES="$SCYTHEBILL/data/src/commonMain/composeResources/files"
java -cp "$CLASSPATH" tools/oracle/Oracle.java "$FILES/taxon.xml" \
    "$SCYTHEBILL/model/src/main/resources/avilist-taxon.xml" "$FIXTURES/corpus.txt" \
    "$FILES/multilingual" "$WORK/out"
"$PY" -I tools/oracle/summarize.py "$WORK/out" "$PACK" "$FIXTURES"

# .bsxm round-trip expectations: Scythebill's own load-upgrade-save (RoundTrip.java).
round_trip() {
    java -cp "$CLASSPATH" tools/oracle/RoundTrip.java "$FILES/taxon.xml" \
        "$SCYTHEBILL/model/src/main/resources/avilist-taxon.xml" \
        "$SCYTHEBILL/app/src/main/resources" "$1" "$2"
}
BSXM=tests/fixtures/bsxm
round_trip "$BSXM/edge_cases.bsxm" "$BSXM/edge_cases.expected.bsxm"
round_trip "$BSXM/edge_cases.expected.bsxm" "$BSXM/edge_cases.expected2.bsxm"
round_trip "$SCYTHEBILL/mobile/app/src/androidDeviceTest/assets/large_sample.bsxm" "$WORK/large_sample.bsxm"
gzip -9 -n -c "$WORK/large_sample.bsxm" > "$BSXM/large_sample.scythebill.bsxm.gz"
java -cp "$CLASSPATH" tools/oracle/NewList.java "$FILES/taxon.xml" "$BSXM/new_list.scythebill.bsxm"
# Your own list, if you want the private test to require Scythebill's exact output:
#   round_trip ~/path/List.bsxm "$WORK/private.expected.bsxm"
#   PIPIT_PRIVATE_BSXM=~/path/List.bsxm PIPIT_PRIVATE_EXPECTED="$WORK/private.expected.bsxm" \
#       .venv/bin/python -m pytest -m private

# Location operations (LocationOps.java) on a fixture of custom places, visits and a trip.
"$PY" -I tools/oracle/make_locations_fixture.py "$PACK" "$BSXM/locations.bsxm"
location_ops() {
    local name="$1"; shift
    java -cp "$CLASSPATH" tools/oracle/LocationOps.java "$FILES/taxon.xml" \
        "$SCYTHEBILL/model/src/main/resources/avilist-taxon.xml" \
        "$SCYTHEBILL/app/src/main/resources" "$BSXM/locations.bsxm" \
        "$BSXM/locations.$name.scythebill.bsxm" "$@"
}
location_ops reassign
location_ops delete delete:lighth
location_ops merge merge:lakmer:bayare
location_ops move move:bayare1:_usst_califo
location_ops merge_recursive merge:coast:poirey

# Editing an existing visit (EditVisit.java: SingleLocationEdit snapshot, edit, apply).
"$PY" -I tools/oracle/make_visits_fixture.py "$BSXM/visits.bsxm"
edit_visit() {
    local name="$1"; shift
    java -cp "$CLASSPATH" tools/oracle/EditVisit.java "$FILES/taxon.xml" \
        "$SCYTHEBILL/model/src/main/resources/avilist-taxon.xml" \
        "$SCYTHEBILL/app/src/main/resources" "$BSXM/visits.bsxm" \
        "$BSXM/visits.$name.scythebill.bsxm" "$@"
}
edit_visit unchanged clements lakmer 2026-08-08 08:00
edit_visit unchanged_avilist avilist lakmer 2026-08-08 08:00
edit_visit edit clements lakmer 2026-08-08 08:00 count:spAnaspla:7 remove:spArdeaalb \
    add:spEgretthu:2 heard:spOxyurjam "comments:Calm, then windy"
edit_visit edit_avilist avilist lakmer 2026-08-08 08:00 count:spAnaspla:7 add:spEgretthu:2
edit_visit add_time clements muiwoo 2026-09-09 06:30 add:spAnasrub:1
edit_visit remove_all clements _scyco_GB-ENG-KEN 2026-06-06 - remove:spAnaspla  # Kent becomes built-in on load

# Trips (TripOps.java: TripsBrowsePanel.deleteTrips and TripInfoBrowsePanel.save).
"$PY" -I tools/oracle/make_trips_fixture.py "$BSXM/trips.bsxm"
trip_ops() {
    local name="$1"; shift
    java -cp "$CLASSPATH" tools/oracle/TripOps.java "$FILES/taxon.xml" \
        "$SCYTHEBILL/model/src/main/resources/avilist-taxon.xml" \
        "$SCYTHEBILL/app/src/main/resources" "$BSXM/trips.bsxm" \
        "$BSXM/trips.$name.scythebill.bsxm" "$@"
}
trip_ops delete_coast delete:coast
trip_ops delete_spring delete:spring
trip_ops delete_oneday delete:oneday
trip_ops delete_span delete:span
trip_ops edit "edit:coast:name=Oregon coast|start=2026-06-30|end=2026-07-09|notes=Fog, then sun"
trip_ops move edit:coast:loc=bayare1
trip_ops clear_notes "edit:coast:notes="
