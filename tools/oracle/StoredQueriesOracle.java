// Stored queries through Scythebill's own StoredQueries and ReportPreferencesManager:
//   StoredQueriesOracle taxon.xml avilist.xml appResources in.bsxm out.bsxm ops.jsonl
// Loads the list (with Scythebill's upgrades), prints the stored queries as Scythebill
// restores them (one JSON line each: name, persisted, type), applies each op in ops.jsonl
// (one JSON object a line: add, ticks, remove, rename or move) with StoredQueries' own
// methods, each of which saves the preferences, and writes the list. An empty ops file
// leaves the list's preferences as they were (restoring never marks the list dirty).
// Compiled into Scythebill's reports package (package-private constructors); see run.sh.
package com.scythebill.birdlist.ui.panels.reports;

import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
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
import com.scythebill.birdlist.model.taxa.TaxonomyMappings;
import com.scythebill.birdlist.model.xml.XmlReportSetExport;
import com.scythebill.birdlist.model.xml.XmlReportSetImport;
import com.scythebill.birdlist.model.xml.XmlTaxonImport;
import com.scythebill.birdlist.ui.prefs.ReportPreferencesManager;
import com.scythebill.birdlist.ui.prefs.ReportSetPreference;
import java.io.*;
import java.lang.reflect.Constructor;
import java.nio.charset.StandardCharsets;
import java.nio.file.Paths;

public class StoredQueriesOracle {
  public static void main(String[] args) throws Exception {
    Taxonomy clements;
    try (Reader r = QueryOracle.reader(args[0])) {
      clements = new XmlTaxonImport().importTaxa(r);
    }
    MappedTaxonomy avilist;
    try (Reader r = QueryOracle.reader(args[1])) {
      avilist = new XmlTaxonImport().importMappedTaxa(r, clements);
    }
    Injector injector = Guice.createInjector(new UpgraderModule(), new AbstractModule() {
      @Provides @Singleton PredefinedLocations predefinedLocations() {
        return PredefinedLocations.loadAndParse();
      }
    });
    Checklists checklists = injector.getInstance(Checklists.class);
    TaxonomyMappings mappings =
        new TaxonomyMappings(QueryOracle.loaders(Paths.get(args[2])), checklists);
    ReportSet reportSet;
    try (Reader r = QueryOracle.reader(args[3])) {
      reportSet = new XmlReportSetImport().importReportSet(
          r, clements, com.google.common.base.Optional.of(avilist), mappings);
    }
    injector.getInstance(OneTimeUpgradeProcessor.class).upgradeReportSet(reportSet);
    injector.getInstance(UpgraderProcessing.class).upgradeReportSet(reportSet);
    PredefinedLocationPopulator.populate(
        reportSet.getLocations(), injector.getInstance(PredefinedLocations.class));

    // As ReportSetModule wires it: one manager over the list's preferences, Gson as
    // CommonModule provides it.
    var manager = new ReportPreferencesManager(
        reportSet, new GsonBuilder().setPrettyPrinting().create());
    Constructor<ReportSetPreference> constructor = ReportSetPreference.class
        .getDeclaredConstructor(Object.class, ReportPreferencesManager.class);
    constructor.setAccessible(true);
    @SuppressWarnings("unchecked")
    ReportSetPreference<StoredReportSetQueriesPreferences> preference = constructor.newInstance(
        manager.getPreference(StoredReportSetQueriesPreferences.class), manager);
    // The factory is only used to run a query, never here.
    var stored = new StoredQueries(null, null, new StoredQueriesPreferences(), preference);

    for (var query : stored.getStoredQueries()) {
      var out = new JsonObject();
      out.addProperty("name", query.getName());
      String persisted = query.queryJson();
      if (query.getStoredQueryType() == StoredQueries.StoredQueryType.TOTAL_TICKS) {
        persisted = query.getTotalTickType().name() + "/" + persisted;
      }
      out.addProperty("persisted", persisted);
      out.addProperty("type", query.getStoredQueryType().name());
      System.out.println(out);
    }

    for (String line : java.nio.file.Files.readAllLines(Paths.get(args[5]))) {
      if (line.isBlank()) continue;
      JsonObject op = JsonParser.parseString(line).getAsJsonObject();
      String name = op.has("name") ? op.get("name").getAsString() : null;
      switch (op.get("op").getAsString()) {
        case "add" -> stored.addReportsQuery(name, op.get("json").getAsString());
        case "ticks" -> stored.addTotalTicksQuery(name,
            TotalTicksProcessor.TotalTickType.valueOf(op.get("ticks").getAsString()), op.get("json").getAsString());
        case "remove" -> stored.removeQuery(find(stored, name));
        case "rename" -> stored.renameQuery(find(stored, name), op.get("to").getAsString());
        case "move" -> stored.moveQuery(op.get("from").getAsInt(), op.get("to").getAsInt());
        default -> throw new IllegalArgumentException(line);
      }
    }

    try (Writer w = new OutputStreamWriter(new FileOutputStream(args[4]), StandardCharsets.UTF_8)) {
      new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
    }
  }

  static StoredQueries.StoredQuery find(StoredQueries stored, String name) {
    return stored.getStoredQueries().stream()
        .filter(query -> query.getName().equals(name)).findFirst().orElseThrow();
  }
}
