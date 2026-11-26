// Prints reports through Scythebill's own HtmlOutput, as its Print button does, and lists the
// checklist Scythebill finds for each place (Checklists.getChecklist):
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm print cases.jsonl outDir
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm xlsx cases.jsonl outDir
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm checklists out.jsonl
//   PrintOracle taxon.xml avilist.xml appResources in.bsxm family cases.jsonl outDir
// Each print case is one line of JSON:
//   {"name", "query": {stored query}, "display": "clements"|"avilist", "depth",
//    "fileName", "date", "namesOrder": ScientificOrCommon, "options": ReportPrintPreferences}
// and is written to outDir/<name>.html. Everything PrintAction does is here, with the
// ReportsPanel query executor it is given (the query restored as StoredQueries restores it,
// the single location's checklist, QueryPreferences' countable predicate) and with the date
// and file name taken from the case. The xlsx mode does what SaveAsXlsAction does instead
// (options: ReportSpreadsheetPreferences), to outDir/<name>.xlsx.
// The checklists mode writes, for every place in use in the list and every synthetic place,
// in both taxonomies, the checklist's size and a SHA-256 of its sorted "taxon=STATUS" lines
// (and for a synthetic place, the codes its checklist is the union of).
// The status mode writes, for each of ChecklistStatusReportPanel's choices in both
// taxonomies, the places it lists (id, whether the checklist is custom) with their species.
// The family mode writes outDir/<name>.json: the checklist's places (sorted ids), whether there
// is a checklist, [id, seen, total] for each ORDER, FAMILY and GENUS in taxonomic order, and the
// seen and total species.
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
import com.scythebill.birdlist.ui.io.ReportXlsOutput;
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
  static Checklists CHECKLISTS;

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
    CHECKLISTS = checklists;
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
    if (args[4].equals("status")) {
      writeChecklistStatus(reportSet, checklists, clements, avilist, args[5]);
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
    String mode = args[4];
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

      if (mode.equals("family")) {
        writeFamily(testCase, reportSet, taxonomy, restored, fields, operations, locations,
            queryPreferences, checklists, outDir);
        continue;
      }

      JsonObject options = testCase.getAsJsonObject("options");
      Checklist singleChecklist = null;
      if (locations.size() == 1) {
        Location location = locations.iterator().next();
        if (location != null) {
          singleChecklist = checklists.getChecklist(reportSet, taxonomy, location);
        }
      }
      if (mode.equals("xlsx")) {
        writeSpreadsheet(testCase, options, reportSet, taxonomy, depth, restored,
            queryPreferences, singleChecklist, rootLocation, reportHints, locationNames,
            new File(outDir, testCase.get("name").getAsString() + ".xlsx"));
        continue;
      }
      if (mode.equals("csv")) {
        // ScythebillCsvExportAction: ReportsPanel's query, in the display taxonomy and depth
        QueryProcessor processor = new QueryProcessor(reportSet, taxonomy, singleChecklist, null);
        processor.keepInvalidSightingsAfterUpdate();
        QueryResults csvResults = processor.runQuery(
            restored.rawQueryDefinition(taxonomy, reportSet, depth),
            restored.countablePredicate(taxonomy, queryPreferences), depth);
        var export = new com.scythebill.birdlist.model.export.FullReportExport();
        if (testCase.has("excel") && testCase.get("excel").getAsBoolean()) {
          export.useExcelCompatibleCsv();
        }
        export.exportReportSet(com.google.common.io.Files.asByteSink(
            new File(outDir, testCase.get("name").getAsString() + ".csv")),
            reportSet, taxonomy, csvResults);
        continue;
      }
      if (mode.equals("ebird")) {
        writeEBird(reportSet, clements, restored, queryPreferences, singleChecklist, outDir,
            testCase.get("name").getAsString());
        continue;
      }
      if (mode.equals("trip")) {
        String caseName = testCase.get("name").getAsString();
        try {
          writeTripReport(testCase, options, reportSet, taxonomy, depth, restored,
              queryPreferences, singleChecklist, rootLocation, reportName, locationNames,
              outDir, caseName);
        } catch (UnsupportedOperationException | NullPointerException e) {
          // Scythebill can't write this one (a synthetic region has no parent to ask for; a
          // trip with no place has a sighting with no place)
          Files.writeString(new File(outDir, caseName + ".error").toPath(), e.toString());
        }
        continue;
      }
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
          ScientificOrCommon.valueOf(testCase.get("namesOrder").getAsString()),
          prefs.includeScientific);

      // ReportsPanel.executeQuery
      QueryProcessor processor =
          new QueryProcessor(reportSet, taxonomy, singleChecklist, null);
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

  /** SaveAsXlsAction.actionPerformed, with ReportsPanel's query executor. */
  static void writeSpreadsheet(JsonObject testCase, JsonObject options, ReportSet reportSet,
      Taxonomy taxonomy, Taxon.Type depth, StoredQueries.RestoredQuery restored,
      QueryPreferences queryPreferences, Checklist checklist, Location rootLocation,
      Set<ReportHints> reportHints, LocationNames locationNames, File out) throws Exception {
    ReportSpreadsheetPreferences prefs = new ReportSpreadsheetPreferences();
    prefs.includeScientific = options.get("includeScientific").getAsBoolean();
    prefs.showFamilies = options.get("showFamilies").getAsBoolean();
    prefs.showStatus = options.get("showStatus").getAsBoolean();
    prefs.showNotes = options.get("showNotes").getAsBoolean();
    prefs.onlyCountable = options.get("onlyCountable").getAsBoolean();
    prefs.omitSpAndHybrid = options.get("omitSpAndHybrid").getAsBoolean();
    prefs.maximumSightings = options.get("maximumSightings").getAsInt();
    prefs.sortType = SortType.valueOf(options.get("sortType").getAsString());
    prefs.sortSightingsType = SortType.valueOf(options.get("sortSightingsType").getAsString());
    prefs.userOutput = UserOutput.valueOf(options.get("userOutput").getAsString());
    prefs.subspeciesInSeparateColumn = options.get("subspeciesInSeparateColumn").getAsBoolean();
    boolean hasSubspecies = depth != Taxon.Type.species;

    QueryProcessor processor = new QueryProcessor(reportSet, taxonomy, checklist, null);
    processor.keepInvalidSightingsAfterUpdate();
    if (prefs.onlyCountable) {
      processor.onlyIncludeCountableSightings();
    }
    QueryResults queryResults = processor.runQuery(
        restored.rawQueryDefinition(taxonomy, reportSet, depth),
        restored.countablePredicate(taxonomy, queryPreferences), depth);

    ReportXlsOutput output = new ReportXlsOutput(
        out, queryResults, reportSet.getLocations(), locationNames);
    output.setScientificOrCommon(scientificOrCommon(
        ScientificOrCommon.valueOf(testCase.get("namesOrder").getAsString()),
        prefs.includeScientific));
    output.setShowFamilies(prefs.showFamilies);
    output.setShowFamilyTotals(!reportHints.contains(ReportHints.SPECIES_STATUS_RESTRICTION));
    output.setRootLocation(rootLocation);
    output.setSightingsCount(prefs.maximumSightings);
    output.setShowStatus(prefs.showStatus);
    output.setShowNotes(prefs.showNotes);
    output.setShowAllTaxonomies(false);
    output.setOmitSpAndHybrid(prefs.omitSpAndHybrid);
    output.setSubspeciesInSeparateColumn(hasSubspecies && prefs.subspeciesInSeparateColumn);
    output.setUserOutput(reportSet.getUserSet() == null ? UserOutput.NONE : prefs.userOutput);
    output.writeSpeciesList(prefs.sortType, prefs.sortSightingsType.ordering());
  }

  /**
   * SaveAsTripReportAction.actionPerformed, with ReportsPanel's query executor (trips null, so
   * they're matched from the sightings) or the given trips. The lifers and matching trips are
   * Scythebill's own private methods, called by reflection. Writes the HTML, the plain-text
   * copy and the Word document.
   */
  static void writeTripReport(JsonObject testCase, JsonObject options, ReportSet reportSet,
      Taxonomy taxonomy, Taxon.Type depth, StoredQueries.RestoredQuery restored,
      QueryPreferences queryPreferences, Checklist checklist, Location rootLocation,
      com.google.common.base.Optional<String> reportName, LocationNames locationNames,
      File outDir, String name) throws Exception {
    TripReportPreferences prefs = new TripReportPreferences();
    prefs.includeScientific = options.get("includeScientific").getAsBoolean();
    prefs.includeItinerary = options.get("includeItinerary").getAsBoolean();
    prefs.includeSpeciesTable = options.get("includeSpeciesTable").getAsBoolean();
    prefs.includeSpeciesList = options.get("includeSpeciesList").getAsBoolean();
    prefs.showStatus = options.get("showStatus").getAsBoolean();
    prefs.lifersInBold = options.get("lifersInBold").getAsBoolean();

    QueryResults queryResults;
    List<com.scythebill.birdlist.model.sighting.Trip> givenTrips = null;
    if (testCase.has("trips")) {
      givenTrips = new ArrayList<>();
      for (var tripId : testCase.getAsJsonArray("trips")) {
        for (var trip : reportSet.getTrips().allTrips()) {
          if (trip.id().equals(tripId.getAsString())) {
            givenTrips.add(trip);
          }
        }
      }
    }
    if (testCase.has("fromTrips") && testCase.get("fromTrips").getAsBoolean()) {
      // TripsBrowsePanel.tripsQueryExecutor, with includeIncompatibleSightings: the trips'
      // sightings, their common place as the root, and their checklist codes' checklist
      var trips = givenTrips;
      Checklists checklistsForTrips = CHECKLISTS;
      Checklist tripChecklist = checklistsForTrips.getChecklist(reportSet, taxonomy, null,
          checklistsForTrips.getTripChecklistCodes(reportSet, taxonomy, trips));
      rootLocation = com.scythebill.birdlist.model.sighting.TripUtils.getLocationRoot(
          reportSet, trips);
      reportName = com.google.common.base.Optional.absent();
      QueryProcessor processor = new QueryProcessor(reportSet, taxonomy, tripChecklist,
          new LinkedHashMap<>());
      processor.includingIncompatibleSightings();
      java.util.function.Predicate<com.scythebill.birdlist.model.sighting.Sighting> any =
          sighting -> false;
      for (var trip : trips) {
        any = any.or(com.scythebill.birdlist.model.sighting.TripUtils.tripPredicate(
            reportSet, trip, null));
      }
      queryResults = processor.runQuery(any, queryPreferences.getCountablePredicate(
          taxonomy, false, QueryPreferences.HeardOnlyFilter.USE_PREFERENCE), depth);
    } else {
      // ReportsPanel.executeQuery, with includeIncompatibleSightings
      QueryProcessor processor = new QueryProcessor(reportSet, taxonomy, checklist,
          new LinkedHashMap<>());
      processor.keepInvalidSightingsAfterUpdate();
      processor.includingIncompatibleSightings();
      queryResults = processor.runQuery(
          restored.rawQueryDefinition(taxonomy, reportSet, depth),
          restored.countablePredicate(taxonomy, queryPreferences), depth);
    }
    // TripReportDialog: no species table for no visits or too many
    if (queryResults.getAllVisitInfoKeys().size() > 200
        || queryResults.getAllVisitInfoKeys().isEmpty()) {
      prefs.includeSpeciesTable = false;
    }

    var action = new SaveAsTripReportAction(reportSet, null, null, null, null, null,
        locationNames, null, queryPreferences, null, null);
    var computeLifers = SaveAsTripReportAction.class.getDeclaredMethod("computeLiferTaxonIds",
        QueryResults.class, Taxonomy.class, java.util.function.Predicate.class);
    computeLifers.setAccessible(true);
    var matchingTrips = SaveAsTripReportAction.class.getDeclaredMethod("matchingTrips",
        QueryResults.class);
    matchingTrips.setAccessible(true);

    var output = new com.scythebill.birdlist.ui.io.TripReportDocOutput(
        queryResults, reportSet, rootLocation, locationNames);
    reportName.toJavaUtil().ifPresent(output::setName);
    output.setScientificOrCommon(scientificOrCommon(
        ScientificOrCommon.valueOf(testCase.get("namesOrder").getAsString()),
        prefs.includeScientific));
    output.setWriteItinerary(prefs.includeItinerary);
    output.setWriteSpeciesList(prefs.includeSpeciesList);
    output.setWriteSpeciesTable(prefs.includeSpeciesTable);
    output.setShowStatus(prefs.showStatus);
    output.setLifersInBold(prefs.lifersInBold);
    java.util.function.Predicate<com.scythebill.birdlist.model.sighting.Sighting> countable =
        queryPreferences.getCountablePredicate(queryResults.getTaxonomy(), false,
            QueryPreferences.HeardOnlyFilter.USE_PREFERENCE);
    if (countable == null) {
      countable = sighting -> true;
    }
    output.setCountablePredicate(countable);
    output.setUseMiles(testCase.get("useMiles").getAsBoolean());
    Map<Taxonomy, Set<String>> liferTaxonIds = new LinkedHashMap<>();
    @SuppressWarnings("unchecked")
    Set<String> lifers = (Set<String>) computeLifers.invoke(
        action, queryResults, queryResults.getTaxonomy(), countable);
    liferTaxonIds.put(queryResults.getTaxonomy(), lifers);
    output.setLiferTaxonIds(liferTaxonIds);
    output.setShowAllTaxonomies(false);
    output.setIncludeFavoritePhotos(false);
    if (givenTrips != null) {
      output.setTrips(givenTrips);
    } else {
      @SuppressWarnings("unchecked")
      Collection<com.scythebill.birdlist.model.sighting.Trip> trips =
          (Collection<com.scythebill.birdlist.model.sighting.Trip>) matchingTrips.invoke(
              action, queryResults);
      output.setTrips(trips);
    }

    StringWriter html = new StringWriter();
    String plainText = output.writeReport(html);
    Files.writeString(new File(outDir, name + ".html").toPath(), html.toString(),
        StandardCharsets.UTF_8);
    Files.writeString(new File(outDir, name + ".txt").toPath(), plainText,
        StandardCharsets.UTF_8);
    try (OutputStream out = new FileOutputStream(new File(outDir, name + ".docx"))) {
      output.writeWordDocument(out);
    }
  }

  /**
   * EbirdExportAction.actionPerformed: the query run in Clements at group depth (as the
   * Reports screen runs it), sightings newest first then in taxonomic order, written with
   * EBirdCsvExport to name.csv, then name-1.csv... past 900K each.
   */
  static void writeEBird(ReportSet reportSet, Taxonomy clements,
      StoredQueries.RestoredQuery restored, QueryPreferences queryPreferences,
      Checklist checklist, File outDir, String name) throws Exception {
    QueryProcessor processor = new QueryProcessor(reportSet, clements, checklist, null);
    processor.keepInvalidSightingsAfterUpdate();
    QueryResults queryResults = processor.runQuery(
        restored.rawQueryDefinition(clements, reportSet, Taxon.Type.group),
        restored.countablePredicate(clements, queryPreferences), Taxon.Type.group);
    List<com.scythebill.birdlist.model.sighting.Sighting> sightings =
        com.google.common.collect.Lists.newArrayList(queryResults.getAllSightings());
    java.util.Collections.sort(sightings,
        com.scythebill.birdlist.model.query.SightingComparators.preferEarlier().compound(
            com.scythebill.birdlist.model.query.SightingComparators.inTaxonomicOrder(clements))
            .reversed());
    var iterator = sightings.iterator();
    int loopCount = 0;
    var namesPreferences = new com.scythebill.birdlist.model.taxa.names.NamesPreferences();
    do {
      File out = new File(outDir, loopCount == 0 ? name + ".csv" : name + "-" + loopCount + ".csv");
      new com.scythebill.birdlist.model.export.EBirdCsvExport(clements, namesPreferences)
          .writeSpeciesList(com.google.common.io.Files.asByteSink(out), iterator, queryResults,
              reportSet);
      loopCount++;
    } while (iterator.hasNext());
  }

  /** ReportPrintDialog (and ReportXlsDialog).getScientificOrCommonFromConfiguration. */
  static ScientificOrCommon scientificOrCommon(ScientificOrCommon preference,
      boolean includeScientific) {
    if (includeScientific) {
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

  /**
   * The family report's counts (FamilyReportPanel.recompute and rebuildTotals, with default
   * preferences: extinct species shown, undescribed ones not counted) at each group level.
   */
  static void writeFamily(JsonObject testCase, ReportSet reportSet, Taxonomy taxonomy,
      StoredQueries.RestoredQuery restored, List<QueryFieldFactory.QueryFieldValue> fields,
      List<CompositeQueryDefinition.BooleanOperation> operations, Set<Location> locations,
      QueryPreferences queryPreferences, Checklists checklists, File outDir) throws IOException {
    var queryDefinition = restored.rawQueryDefinition(taxonomy, reportSet, Taxon.Type.species);
    var countablePredicate = restored.countablePredicate(taxonomy, queryPreferences);
    var excludedStatuses = FamilyReportComputation.excludedStatuses(
        queryPreferences.excludedChecklistStatuses(), true);
    // QueryPanel.getTaxonEligibilityPredicate, over the restored fields
    com.google.common.collect.Multimap<Class<?>, java.util.function.Predicate<Taxon>> included =
        com.google.common.collect.ArrayListMultimap.create();
    com.google.common.collect.Multimap<Class<?>, java.util.function.Predicate<Taxon>> excluded =
        com.google.common.collect.ArrayListMultimap.create();
    for (int i = 0; i < fields.size(); i++) {
      var field = fields.get(i);
      com.google.common.base.Optional<java.util.function.Predicate<Taxon>> predicate =
          com.google.common.base.Optional.absent();
      if (field instanceof FamilyQueryField.Value value) {
        predicate = value.taxonPredicate();
      } else if (field instanceof SpeciesStatusQueryField.Value value) {
        predicate = value.taxonPredicate();
      }
      if (!predicate.isPresent()) {
        continue;
      }
      var operation = operations.get(i);
      if (operation == CompositeQueryDefinition.BooleanOperation.NEVER
          || operation == CompositeQueryDefinition.BooleanOperation.NEVER_ALL) {
        excluded.put(field.getClass(), predicate.get());
      } else {
        included.put(field.getClass(), predicate.get());
      }
    }
    List<java.util.function.Predicate<Taxon>> perType = new ArrayList<>();
    for (Class<?> type : com.google.common.collect.Sets.union(included.keySet(), excluded.keySet())) {
      List<java.util.function.Predicate<Taxon>> in = new ArrayList<>(included.get(type));
      List<java.util.function.Predicate<Taxon>> out = new ArrayList<>(excluded.get(type));
      perType.add(taxon -> (in.isEmpty() || in.stream().anyMatch(p -> p.test(taxon)))
          && out.stream().noneMatch(p -> p.test(taxon)));
    }
    java.util.function.Predicate<Taxon> eligibility =
        taxon -> perType.stream().allMatch(p -> p.test(taxon));

    var synthesizer = new com.scythebill.birdlist.model.checklist.ChecklistSynthesizer(
        checklists, reportSet, PredefinedLocations.loadAndParse());
    List<Location> queryLocations = new ArrayList<>();
    for (Location location : locations) {
      if (location != null) {
        queryLocations.add(location);
      }
    }
    var scope = FamilyReportComputation.resolveScope(
        checklists, synthesizer, reportSet, taxonomy, queryLocations);
    var seen = FamilyReportComputation.seenSpeciesIds(
        reportSet, taxonomy, queryDefinition, countablePredicate);
    var speciesFilter = FamilyReportComputation.speciesFilter(false, true, eligibility, seen);

    JsonObject out = new JsonObject();
    out.addProperty("name", testCase.get("name").getAsString());
    var scopeIds = new com.google.gson.JsonArray();
    scope.checklistLocations().stream().map(Location::getId).sorted().forEach(scopeIds::add);
    out.add("scope", scopeIds);
    out.addProperty("checklist", scope.checklist() != null);
    for (Taxon.Type type : List.of(Taxon.Type.order, Taxon.Type.family, Taxon.Type.genus)) {
      FamilyReportTotals totals = FamilyReportTotals.compute(taxonomy, type, scope.checklist(),
          excludedStatuses, speciesFilter, seen);
      var groups = new com.google.gson.JsonArray();
      for (var group : totals.groups()) {
        var row = new com.google.gson.JsonArray();
        row.add(group.group().getId());
        row.add(group.seen());
        row.add(group.total());
        groups.add(row);
      }
      out.add(type.name().toUpperCase(Locale.ROOT), groups);
      out.addProperty("seen", totals.seenSpecies());
      out.addProperty("total", totals.totalSpecies());
    }
    Files.writeString(new File(outDir, testCase.get("name").getAsString() + ".json").toPath(),
        out.toString());
  }


  /**
   * ChecklistStatusReportPanel.showReport for each of its choices, in both taxonomies: the
   * places in the order the report lists them (whether each checklist is custom) and the
   * species listed under each, as one line of JSON per taxonomy and choice.
   */
  static void writeChecklistStatus(ReportSet reportSet, Checklists checklists,
      Taxonomy clements, Taxonomy avilist, String outFile) throws IOException {
    var lines = new ArrayList<String>();
    for (Taxonomy taxonomy : List.of(clements, avilist)) {
      // The sightings at each place with a checklist (and at each such place above them)
      com.google.common.collect.Multimap<Location, SightingTaxon> byLocation =
          com.google.common.collect.LinkedHashMultimap.create();
      for (var sighting : reportSet.getSightings(taxonomy)) {
        if (sighting.getLocationId() == null) {
          continue;
        }
        Location location = reportSet.getLocations().getLocation(sighting.getLocationId());
        var status = sighting.getSightingInfo().getSightingStatus();
        String statusName = status.name();
        if (statusName.equals("INTRODUCED_NOT_ESTABLISHED") || statusName.equals("ID_UNCERTAIN")
            || statusName.equals("DOMESTIC") || statusName.equals("RECORD_NOT_ACCEPTED")) {
          continue;
        }
        while (location != null) {
          if (checklists.hasChecklist(taxonomy, reportSet, location)) {
            byLocation.put(location, sighting.getTaxon());
          }
          location = location.getParent();
        }
      }
      for (String choice : List.of("NOT_FOUND", "RARITY", "ENDEMIC", "ESCAPED", "EXTINCT",
          "INTRODUCED", "PROVISIONAL")) {
        com.google.common.collect.ListMultimap<Location,
            SightingTaxon.Resolved> matching =
            com.google.common.collect.ArrayListMultimap.create();
        for (Location location : byLocation.keySet()) {
          Checklist checklist = checklists.getChecklist(reportSet, taxonomy, location);
          if (checklist == null || checklist.isSynthetic()) {
            continue;
          }
          for (SightingTaxon taxon : byLocation.get(location)) {
            var resolved = taxon.resolve(taxonomy);
            if (resolved.getSmallestTaxonType() != Taxon.Type.species) {
              resolved = resolved.getParentOfAtLeastType(Taxon.Type.species)
                  .resolveInternal(taxonomy);
            }
            if (resolved.getType() != SightingTaxon.Type.SINGLE
                && resolved.getType() != SightingTaxon.Type.SINGLE_WITH_SECONDARY_SUBSPECIES) {
              continue;
            }
            Checklist.Status status = checklist.getStatus(taxonomy, resolved.getSightingTaxon());
            boolean matches = switch (choice) {
              case "NOT_FOUND" -> status == null;
              case "RARITY" -> status == Checklist.Status.RARITY
                  || status == Checklist.Status.RARITY_FROM_INTRODUCED;
              default -> status != null && status.name().equals(choice);
            };
            if (matches) {
              matching.put(location, resolved);
            }
          }
        }
        JsonObject out = new JsonObject();
        out.addProperty("taxonomy", taxonomy == avilist ? "avilist" : "clements");
        out.addProperty("choice", choice);
        var places = new com.google.gson.JsonArray();
        for (Location root : reportSet.getLocations().rootLocations()) {
          appendStatusPlaces(places, matching, root, reportSet, checklists, taxonomy);
        }
        out.add("places", places);
        lines.add(out.toString());
      }
    }
    Files.write(Paths.get(outFile), lines, StandardCharsets.UTF_8);
  }

  private static void appendStatusPlaces(com.google.gson.JsonArray places,
      com.google.common.collect.ListMultimap<Location,
          SightingTaxon.Resolved> matching,
      Location location, ReportSet reportSet, Checklists checklists, Taxonomy taxonomy) {
    if (matching.containsKey(location)) {
      Checklist checklist = checklists.getChecklist(reportSet, taxonomy, location);
      var sorted = com.google.common.collect.ImmutableSortedSet.copyOf(
          new com.scythebill.birdlist.model.util.ResolvedComparator(), matching.get(location));
      JsonObject place = new JsonObject();
      place.addProperty("id", location.getId());
      place.addProperty("custom", !checklist.isBuiltIn());
      var taxa = new com.google.gson.JsonArray();
      for (var resolved : sorted) {
        taxa.add(resolved.getTaxon().getId());
      }
      place.add("taxa", taxa);
      places.add(place);
    }
    for (Location child : location.contents()) {
      appendStatusPlaces(places, matching, child, reportSet, checklists, taxonomy);
    }
  }

}
