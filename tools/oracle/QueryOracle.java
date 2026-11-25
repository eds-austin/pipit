// Runs stored queries through Scythebill's own headless query path, the way its Reports
// screen counts them, and prints one line of JSON per query:
//   QueryOracle taxon.xml avilist.xml appResources in.bsxm DISPLAY DEPTH queries.txt
// DISPLAY is clements or avilist; DEPTH species, group or subspecies. queries.txt has one
// stored query's JSON per line (the "json" of a stored query: {"fields":[...]}).
// Each query: StoredQueries.restore's parsing (QueryFieldType.parseValue), then
// CompositeQueryDefinition.forValues, QueryPreferences' countable predicate (defaults, with
// the query's status and heard-only overrides), QueryProcessor as ReportsPanel runs it
// (keeping invalid sightings), and ReportsPanel's totals.
// Compiled into Scythebill's reports package (it uses package-private classes); see run.sh.
package com.scythebill.birdlist.ui.panels.reports;

import com.google.common.base.Charsets;
import com.google.common.io.Files;
import com.google.inject.AbstractModule;
import com.google.inject.Guice;
import com.google.inject.Injector;
import com.google.inject.Provides;
import com.google.inject.Singleton;
import com.scythebill.birdlist.model.checklist.Checklists;
import com.scythebill.birdlist.model.sighting.PredefinedLocationPopulator;
import com.scythebill.birdlist.model.sighting.PredefinedLocations;
import com.scythebill.birdlist.model.sighting.ReportSet;
import com.scythebill.birdlist.model.sighting.upgrades.OneTimeUpgradeProcessor;
import com.scythebill.birdlist.model.sighting.upgrades.UpgraderModule;
import com.scythebill.birdlist.model.sighting.upgrades.UpgraderProcessing;
import com.scythebill.birdlist.model.taxa.MappedTaxonomy;
import com.scythebill.birdlist.model.taxa.Taxonomy;
import com.scythebill.birdlist.model.taxa.TaxonomyMappingLoader;
import com.scythebill.birdlist.model.taxa.TaxonomyMappings;
import com.scythebill.birdlist.model.xml.XmlReportSetExport;
import com.scythebill.birdlist.model.xml.XmlReportSetImport;
import com.scythebill.birdlist.model.xml.XmlTaxonImport;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.*;
import java.util.regex.*;

public class QueryOracle {
  public static void main(String[] args) throws Exception {
    Taxonomy clements;
    try (Reader r = reader(args[0])) {
      clements = new XmlTaxonImport().importTaxa(r);
    }
    MappedTaxonomy avilist;
    try (Reader r = reader(args[1])) {
      avilist = new XmlTaxonImport().importMappedTaxa(r, clements);
    }
    Injector injector = Guice.createInjector(new UpgraderModule(), new AbstractModule() {
      @Provides @Singleton PredefinedLocations predefinedLocations() {
        return PredefinedLocations.loadAndParse();
      }
    });
    Checklists checklists = injector.getInstance(Checklists.class);
    TaxonomyMappings mappings = new TaxonomyMappings(loaders(Paths.get(args[2])), checklists);

    ReportSet reportSet;
    try (BufferedReader r = new BufferedReader(reader(args[3]))) {
      String first = r.readLine();
      // ReportSetLoader strips a UTF-8 BOM.
      String text = (first != null && first.startsWith("﻿") ? first.substring(1) : first);
      StringBuilder all = new StringBuilder(text == null ? "" : text).append('\n');
      char[] buffer = new char[1 << 16];
      int n;
      while ((n = r.read(buffer)) > 0) all.append(buffer, 0, n);
      reportSet = new XmlReportSetImport().importReportSet(
          new StringReader(all.toString()), clements, com.google.common.base.Optional.of(avilist), mappings);
    }
    injector.getInstance(OneTimeUpgradeProcessor.class).upgradeReportSet(reportSet);
    injector.getInstance(UpgraderProcessing.class).upgradeReportSet(reportSet);
    PredefinedLocationPopulator.populate(
        reportSet.getLocations(), injector.getInstance(PredefinedLocations.class));

    Taxonomy display = args[4].equals("avilist") ? avilist : clements;
    var depth = com.scythebill.birdlist.model.taxa.Taxon.Type.valueOf(args[5]);
    var eventBus = new com.google.common.eventbus.EventBus();
    var taxonomyStore = new com.scythebill.birdlist.ui.events.TaxonomyStore(eventBus, clements,
        avilist, new com.scythebill.birdlist.ui.events.TaxonomyPreferences(), reportSet,
        com.scythebill.birdlist.ui.prefs.ReportSetPreference.staticValue(
            new com.scythebill.birdlist.ui.events.TaxonomyPreferences.PerReportSet()));
    taxonomyStore.setTaxonomy(display);
    var locationNames = new com.scythebill.birdlist.ui.util.LocationNames(
        new com.scythebill.birdlist.ui.panels.UIPreferences(),
        new com.scythebill.birdlist.model.taxa.names.NamesPreferences());
    var syntheticLocations = new com.scythebill.birdlist.model.query.SyntheticLocations(
        reportSet.getLocations());
    var defaultUserStore = new com.scythebill.birdlist.ui.events.DefaultUserStore(eventBus,
        reportSet, com.scythebill.birdlist.ui.prefs.ReportSetPreference.staticValue(
            new com.scythebill.birdlist.ui.events.UserPreferences.PerReportSet()),
        new com.scythebill.birdlist.ui.uptodate.UpToDatePreferences());
    var factory = new QueryFieldFactory(reportSet, taxonomyStore, null, null, locationNames,
        syntheticLocations, null, defaultUserStore);
    var queryPreferences = new QueryPreferences(new UndescribedTaxa());
    for (String line : java.nio.file.Files.readAllLines(Paths.get(args[6]))) {
      if (line.isBlank()) continue;
      var query = com.google.gson.JsonParser.parseString(line).getAsJsonObject();
      List<QueryFieldFactory.QueryFieldValue> fields = new ArrayList<>();
      List<CompositeQueryDefinition.BooleanOperation> operations = new ArrayList<>();
      CompositeQueryDefinition.BooleanOperation legacy = query.has("type")
          ? CompositeQueryDefinition.BooleanOperation.valueOf(query.get("type").getAsString())
          : null;
      for (var element : query.get("fields").getAsJsonArray()) {
        var object = element.getAsJsonObject();
        var fieldType = QueryFieldFactory.QueryFieldType.valueOf(object.get("type").getAsString());
        fields.add(fieldType.parseValue(factory, object.get("value")));
        var operation = object.has("bool")
            ? CompositeQueryDefinition.BooleanOperation.valueOf(object.get("bool").getAsString())
            : legacy;
        operations.add(operation == null ? CompositeQueryDefinition.BooleanOperation.ALL : operation);
      }
      var restored = new StoredQueries.RestoredQuery(operations, fields);
      var definition = restored.rawQueryDefinition(display, reportSet, depth);
      var countable = restored.countablePredicate(display, queryPreferences);
      var processor = new com.scythebill.birdlist.model.query.QueryProcessor(reportSet, display);
      processor.keepInvalidSightingsAfterUpdate();
      var results = processor.runQuery(definition, countable, depth);
      var out = new com.google.gson.JsonObject();
      out.addProperty("species", results.getCountableSpeciesSize(display, false));
      out.addProperty("speciesWithSp", results.getCountableSpeciesSize(display, true));
      out.addProperty("groups", results.getCountableGroupsAndSpeciesSize(display, false));
      out.addProperty("subspecies", results.getCountableSubspeciesGroupsAndSpeciesSize(display, false));
      out.addProperty("spuh", results.getSpuhCount());
      out.addProperty("families", results.getFamilyCount(display));
      out.addProperty("sightings", results.getSightingsCount(display));
      var taxa = new com.google.gson.JsonArray();
      for (var resolved : results.getTaxaAsList()) {
        var taxon = resolved.getSightingTaxon();
        taxa.add((results.isCountable(resolved) ? "" : "~") + String.join("/", taxon.getIds()));
      }
      out.add("taxa", taxa);
      System.out.println(out);
    }
  }

  static Reader reader(String path) throws IOException {
    return new InputStreamReader(new FileInputStream(path), StandardCharsets.UTF_8);
  }

  /** The TaxonomyMappingLoaders that ApplicationModule registers. */
  @SuppressWarnings("unchecked")
  static java.util.Set<TaxonomyMappingLoader> loaders(Path appResources) throws IOException {
    Path module = appResources.resolve(
        "../java/com/scythebill/birdlist/app/ApplicationModule.java").normalize();
    String source = java.nio.file.Files.readString(module);
    Pattern loader = Pattern.compile(
        "new\\s+TaxonomyMappingLoader\\(\\s*\"([^\"]+)\"\\s*,\\s*Resources\\.asCharSource\\("
            + "\\s*Resources\\.getResource\\(\\s*\"([^\"]+)\"\\s*\\)"
            + "(?:[^;]*?Resources\\.getResource\\(\\s*\"([^\"]+)\"\\s*\\))?[^;]*;",
        Pattern.DOTALL);
    Matcher m = loader.matcher(source);
    java.util.Set<TaxonomyMappingLoader> result = new HashSet<>();
    while (m.find()) {
      File main = appResources.resolve(m.group(2)).toFile();
      File ssp = m.group(3) == null ? null : appResources.resolve(m.group(3)).toFile();
      result.add(new TaxonomyMappingLoader(m.group(1), Files.asCharSource(main, Charsets.UTF_8),
          ssp == null ? null : Files.asCharSource(ssp, Charsets.UTF_8)));
    }
    return result;
  }
}
