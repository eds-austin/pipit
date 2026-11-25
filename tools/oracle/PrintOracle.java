// Prints reports through Scythebill's own HtmlOutput, as its Print button does, and lists the
// checklist Scythebill finds for each place (Checklists.getChecklist):
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm print cases.jsonl outDir
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm checklists out.jsonl
// Each print case is one line of JSON:
//   {"name", "query": {stored query}, "display": "clements"|"avilist", "depth",
//    "fileName", "date", "namesOrder": ScientificOrCommon, "options": ReportPrintPreferences}
// and is written to outDir/<name>.html. Everything PrintAction does is here, with the
// ReportsPanel query executor it is given (the query restored as StoredQueries restores it,
// the single location's checklist, QueryPreferences' countable predicate) and with the date
// and file name taken from the case.
// The checklists mode writes, for every place in use in the list and every synthetic place,
// in both taxonomies, the checklist's size and a SHA-256 of its sorted "taxon=STATUS" lines
// (and for a synthetic place, the codes its checklist is the union of).
// Compiled into Scythebill's reports package (it uses package-private classes); see run.sh.
package com.scythebill.birdlist.ui.panels.reports;

import com.google.common.collect.ImmutableList;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.inject.AbstractModule;
import com.google.inject.Guice;
import com.google.inject.Injector;
import com.google.inject.Provides;
import com.google.inject.Singleton;
import com.scythebill.birdlist.model.checklist.Checklist;
import com.scythebill.birdlist.model.checklist.Checklists;
import com.scythebill.birdlist.model.query.QueryProcessor;
import com.scythebill.birdlist.model.query.QueryResults;
import com.scythebill.birdlist.model.query.SyntheticLocations;
import com.scythebill.birdlist.model.sighting.Location;
import com.scythebill.birdlist.model.sighting.PredefinedLocationPopulator;
import com.scythebill.birdlist.model.sighting.PredefinedLocations;
import com.scythebill.birdlist.model.sighting.ReportSet;
import com.scythebill.birdlist.model.sighting.SightingTaxon;
import com.scythebill.birdlist.model.sighting.upgrades.OneTimeUpgradeProcessor;
import com.scythebill.birdlist.model.sighting.upgrades.UpgraderModule;
import com.scythebill.birdlist.model.sighting.upgrades.UpgraderProcessing;
import com.scythebill.birdlist.model.taxa.MappedTaxonomy;
import com.scythebill.birdlist.model.taxa.Taxon;
import com.scythebill.birdlist.model.taxa.Taxonomy;
import com.scythebill.birdlist.model.taxa.TaxonomyMappings;
import com.scythebill.birdlist.model.taxa.names.NamesPreferences.ScientificOrCommon;
import com.scythebill.birdlist.model.xml.XmlReportSetImport;
import com.scythebill.birdlist.model.xml.XmlTaxonImport;
import com.scythebill.birdlist.ui.io.HtmlOutput;
import com.scythebill.birdlist.ui.messages.Messages;
import com.scythebill.birdlist.ui.messages.Messages.Name;
import com.scythebill.birdlist.ui.util.LocationNames;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.MessageDigest;
import java.util.*;

public class PrintOracle {
  public static void main(String[] args) throws Exception {
    Locale.setDefault(Locale.US);
    // As ApplicationModule does: built-in places' display names, and synthetic regions' names
    // (from i18n/ next to taxon.xml).
    com.scythebill.birdlist.model.sighting.LocationDisplayNames.INSTANCE.setProvider(
        com.scythebill.birdlist.model.sighting.ResourceBundleLocationDisplayNames.INSTANCE);
    com.scythebill.birdlist.model.query.SyntheticLocationTranslations.INSTANCE.install(
        Files.readString(Paths.get(args[0]).resolveSibling("i18n/synthetic-locations-en.csv")));
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
    TaxonomyMappings mappings = new TaxonomyMappings(
        QueryOracle.loaders(Paths.get(args[2])), checklists);

    ReportSet reportSet;
    try (BufferedReader r = new BufferedReader(QueryOracle.reader(args[3]))) {
      String first = r.readLine();
      String text = (first != null && first.startsWith("﻿") ? first.substring(1) : first);
      StringBuilder all = new StringBuilder(text == null ? "" : text).append('\n');
      char[] buffer = new char[1 << 16];
      int n;
      while ((n = r.read(buffer)) > 0) all.append(buffer, 0, n);
      reportSet = new XmlReportSetImport().importReportSet(new StringReader(all.toString()),
          clements, com.google.common.base.Optional.of(avilist), mappings);
    }
    injector.getInstance(OneTimeUpgradeProcessor.class).upgradeReportSet(reportSet);
    injector.getInstance(UpgraderProcessing.class).upgradeReportSet(reportSet);
    PredefinedLocationPopulator.populate(
        reportSet.getLocations(), injector.getInstance(PredefinedLocations.class));
    var syntheticLocations = new SyntheticLocations(reportSet.getLocations());

    if (args[4].equals("checklists")) {
      writeChecklists(reportSet, syntheticLocations, checklists, clements, avilist, args[5]);
      return;
    }

    var eventBus = new com.google.common.eventbus.EventBus();
    var taxonomyStore = new com.scythebill.birdlist.ui.events.TaxonomyStore(eventBus, clements,
        avilist, new com.scythebill.birdlist.ui.events.TaxonomyPreferences(), reportSet,
        com.scythebill.birdlist.ui.prefs.ReportSetPreference.staticValue(
            new com.scythebill.birdlist.ui.events.TaxonomyPreferences.PerReportSet()));
    var locationNames = new LocationNames(
        new com.scythebill.birdlist.ui.panels.UIPreferences(),
        new com.scythebill.birdlist.model.taxa.names.NamesPreferences());
    var defaultUserStore = new com.scythebill.birdlist.ui.events.DefaultUserStore(eventBus,
        reportSet, com.scythebill.birdlist.ui.prefs.ReportSetPreference.staticValue(
            new com.scythebill.birdlist.ui.events.UserPreferences.PerReportSet()),
        new com.scythebill.birdlist.ui.uptodate.UpToDatePreferences());
    var factory = new QueryFieldFactory(reportSet, taxonomyStore, null, null, locationNames,
        syntheticLocations, null, defaultUserStore);
    var queryPreferences = new QueryPreferences(new UndescribedTaxa());
    java.lang.reflect.Field locationType =
        LocationQueryField.Value.class.getDeclaredField("type");
    locationType.setAccessible(true);
    File outDir = new File(args[6]);
    outDir.mkdirs();

    for (String line : Files.readAllLines(Paths.get(args[5]), StandardCharsets.UTF_8)) {
      if (line.isBlank()) continue;
      JsonObject testCase = JsonParser.parseString(line).getAsJsonObject();
      Taxonomy taxonomy = testCase.get("display").getAsString().equals("avilist")
          ? avilist : clements;
      taxonomyStore.setTaxonomy(taxonomy);
      Taxon.Type depth = Taxon.Type.valueOf(testCase.get("depth").getAsString());
      JsonObject query = testCase.getAsJsonObject("query");
      List<QueryFieldFactory.QueryFieldValue> fields = new ArrayList<>();
      List<CompositeQueryDefinition.BooleanOperation> operations = new ArrayList<>();
      CompositeQueryDefinition.BooleanOperation legacy = query.has("type")
          ? CompositeQueryDefinition.BooleanOperation.valueOf(query.get("type").getAsString())
          : null;
      for (var element : query.get("fields").getAsJsonArray()) {
        var object = element.getAsJsonObject();
        var fieldType = QueryFieldFactory.QueryFieldType.valueOf(
            object.get("type").getAsString());
        fields.add(fieldType.parseValue(factory, object.get("value")));
        var operation = object.has("bool")
            ? CompositeQueryDefinition.BooleanOperation.valueOf(object.get("bool").getAsString())
            : legacy;
        operations.add(operation == null
            ? CompositeQueryDefinition.BooleanOperation.ALL : operation);
      }
      var restored = new StoredQueries.RestoredQuery(operations, fields);

      // QueryPanel.getLocations, getRootLocation and getReportHints, from the restored fields.
      Set<Location> locations = new HashSet<>();
      Location rootLocation = null;
      int locationFields = 0;
      EnumSet<ReportHints> reportHints = EnumSet.noneOf(ReportHints.class);
      List<String> names = new ArrayList<>();
      List<String> abbreviations = new ArrayList<>();
      for (int i = 0; i < fields.size(); i++) {
        var field = fields.get(i);
        boolean never = operations.get(i) == CompositeQueryDefinition.BooleanOperation.NEVER
            || operations.get(i) == CompositeQueryDefinition.BooleanOperation.NEVER_ALL;
        field.name().transform(s -> never
            ? Messages.getFormattedMessage(Name.NEVER_FORMAT, s) : s).toJavaUtil()
            .ifPresent(names::add);
        field.abbreviation().transform(s -> never
            ? Messages.getFormattedMessage(Name.NEVER_FORMAT, s) : s).toJavaUtil()
            .ifPresent(abbreviations::add);
        if (field instanceof LocationQueryField.Value value) {
          Location location = value.id == null ? null : reportSet.getLocations().getLocation(value.id);
          if (location == null && value.id != null) {
            location = syntheticLocations.byId(value.id);
          }
          locations.add(location);
          locationFields++;
          Object type = locationType.get(value);
          rootLocation = location != null
              && (((Enum<?>) type).name().equals("IN") || ((Enum<?>) type).name().equals("IS"))
              ? location : null;
        }
        if (!field.isNoOp()) {
          switch (field.getType()) {
            case LOCATION -> reportHints.add(ReportHints.LOCATION_RESTRICTION);
            case SPECIES_STATUS -> reportHints.add(ReportHints.SPECIES_STATUS_RESTRICTION);
            case DATE -> reportHints.add(ReportHints.DATE_RESTRICTION);
            default -> {}
          }
        }
      }
      if (locationFields > 1) {
        rootLocation = null;
      }
      String joinedNames = String.join(" ", names);
      String joinedAbbreviations = String.join("-", abbreviations).replace(File.separatorChar, '-');
      com.google.common.base.Optional<String> reportName = joinedNames.isEmpty()
          ? com.google.common.base.Optional.absent()
          : com.google.common.base.Optional.of(joinedNames);
      com.google.common.base.Optional<String> reportAbbreviation = joinedAbbreviations.isEmpty()
          ? com.google.common.base.Optional.absent()
          : com.google.common.base.Optional.of(joinedAbbreviations);

      JsonObject options = testCase.getAsJsonObject("options");
      ReportPrintPreferences prefs = new ReportPrintPreferences();
      prefs.includeScientific = options.get("includeScientific").getAsBoolean();
      prefs.showFamilies = options.get("showFamilies").getAsBoolean();
      prefs.showStatus = options.get("showStatus").getAsBoolean();
      prefs.maximumSightings = options.get("maximumSightings").getAsInt();
      prefs.sortType = SortType.valueOf(options.get("sortType").getAsString());
      prefs.sortSightingsType = SortType.valueOf(options.get("sortSightingsType").getAsString());
      prefs.compactPrinting = options.get("compactPrinting").getAsBoolean();
      prefs.onlyCountable = options.get("onlyCountable").getAsBoolean();
      prefs.omitSpAndHybrid = options.get("omitSpAndHybrid").getAsBoolean();
      ScientificOrCommon namesOrder = scientificOrCommon(
          ScientificOrCommon.valueOf(testCase.get("namesOrder").getAsString()), prefs);

      // ReportsPanel.executeQuery
      Checklist checklist = null;
      if (locations.size() == 1) {
        Location location = locations.iterator().next();
        if (location != null) {
          checklist = checklists.getChecklist(reportSet, taxonomy, location);
        }
      }
      QueryProcessor processor = new QueryProcessor(reportSet, taxonomy, checklist, null);
      processor.keepInvalidSightingsAfterUpdate();
      if (prefs.onlyCountable) {
        processor.onlyIncludeCountableSightings();
      }
      QueryResults queryResults = processor.runQuery(
          restored.rawQueryDefinition(taxonomy, reportSet, depth),
          restored.countablePredicate(taxonomy, queryPreferences), depth);

      // PrintAction.actionPerformed
      String fileName = testCase.get("fileName").getAsString();
      String date = testCase.get("date").getAsString();
      com.google.common.base.Optional<String> name = reportName.or(reportAbbreviation);
      String heading = name.or(fileName);
      HtmlOutput htmlOutput = new HtmlOutput(taxonomy, rootLocation, null, locationNames);
      htmlOutput.setPrint(true);
      if (prefs.omitSpAndHybrid) {
        htmlOutput.setOmitSpAndHybrid(prefs.omitSpAndHybrid);
      }
      htmlOutput.setTitle(heading);
      if (name.isPresent()) {
        htmlOutput.setDetails(ImmutableList.of(fileName, date));
        htmlOutput.setDocumentTitle(Messages.getFormattedMessage(
            Name.REPORT_DOCUMENT_TITLE_FORMAT, heading, fileName, date));
      } else {
        htmlOutput.setDetails(ImmutableList.of(date));
        htmlOutput.setDocumentTitle(Messages.getFormattedMessage(
            Name.REPORT_DOCUMENT_TITLE_WITHOUT_NAME_FORMAT, fileName, date));
      }
      htmlOutput.setShowStatus(prefs.showStatus);
      htmlOutput.setCompactOutput(prefs.compactPrinting);
      htmlOutput.setScientificOrCommon(namesOrder);
      htmlOutput.setSightingsCount(prefs.compactPrinting ? 0 : prefs.maximumSightings);
      if (prefs.sortType != SortType.DEFAULT) {
        htmlOutput.setShowFamilyTotals(false);
        htmlOutput.setShowFamilies(false);
      } else {
        boolean showFamilyTotals;
        if (reportHints.contains(ReportHints.SPECIES_STATUS_RESTRICTION)) {
          showFamilyTotals = false;
        } else if (reportHints.contains(ReportHints.LOCATION_RESTRICTION)
            && queryResults.getChecklist(taxonomy) == null) {
          showFamilyTotals = false;
        } else {
          showFamilyTotals = true;
        }
        htmlOutput.setShowFamilyTotals(showFamilyTotals);
        htmlOutput.setShowFamilies(prefs.showFamilies);
      }
      File out = new File(outDir, testCase.get("name").getAsString() + ".html");
      try (Writer writer = new OutputStreamWriter(new FileOutputStream(out),
          StandardCharsets.UTF_8)) {
        htmlOutput.writeSpeciesList(writer, queryResults, prefs.sortType,
            prefs.sortSightingsType.ordering(), reportSet.getLocations());
      }
    }
  }

  /** ReportPrintDialog.getScientificOrCommonFromConfiguration. */
  static ScientificOrCommon scientificOrCommon(ScientificOrCommon preference,
      ReportPrintPreferences prefs) {
    if (prefs.includeScientific) {
      if (preference == ScientificOrCommon.COMMON_ONLY) {
        return ScientificOrCommon.COMMON_FIRST;
      }
    } else if (preference != ScientificOrCommon.COMMON_ONLY) {
      return ScientificOrCommon.COMMON_ONLY;
    }
    return preference;
  }

  static void writeChecklists(ReportSet reportSet, SyntheticLocations syntheticLocations,
      Checklists checklists, Taxonomy clements, Taxonomy avilist, String outPath)
      throws Exception {
    List<Location> places = new ArrayList<>();
    Deque<Location> pending = new ArrayDeque<>(reportSet.getLocations().rootLocations());
    while (!pending.isEmpty()) {
      Location location = pending.pop();
      if (reportSet.getLocations().isInUse(location)) {
        places.add(location);
      }
      pending.addAll(location.contents());
    }
    places.sort(Comparator.comparing(Location::getId));
    for (var synthetic : syntheticLocations.locations()) {
      places.add(synthetic);
    }
    try (PrintWriter out = new PrintWriter(new OutputStreamWriter(
        new FileOutputStream(outPath), StandardCharsets.UTF_8))) {
      for (Location place : places) {
        for (Taxonomy taxonomy : List.of(clements, avilist)) {
          Checklist checklist = checklists.getChecklist(reportSet, taxonomy, place);
          JsonObject line = new JsonObject();
          line.addProperty("place", place.getId());
          line.addProperty("taxonomy", taxonomy == clements ? "clements" : "avilist");
          if (place instanceof com.scythebill.birdlist.model.query.SyntheticLocation synthetic) {
            List<String> union = new ArrayList<>(synthetic.syntheticChecklistUnion());
            Collections.sort(union);
            line.addProperty("union", String.join(",", union));
          }
          if (checklist != null) {
            List<String> entries = new ArrayList<>();
            for (SightingTaxon taxon : checklist.getTaxa(taxonomy)) {
              entries.add(String.join("/", taxon.getIds()) + "="
                  + checklist.getStatus(taxonomy, taxon));
            }
            Collections.sort(entries);
            line.addProperty("size", entries.size());
            line.addProperty("sha256", sha256(String.join("\n", entries)));
          }
          out.println(line);
        }
      }
    }
  }

  static String sha256(String text) throws Exception {
    byte[] digest = MessageDigest.getInstance("SHA-256")
        .digest(text.getBytes(StandardCharsets.UTF_8));
    StringBuilder hex = new StringBuilder();
    for (byte b : digest) hex.append(String.format("%02x", b));
    return hex.toString();
  }
}
