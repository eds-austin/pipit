// Imports files into a .bsxm through Scythebill's own importers, as ImportController does it
// with the choices made in advance, then saves the list:
//   ImportOracle taxon.xml avilist.xml appResources in.bsxm cases.jsonl outDir
// Each case is one line of JSON:
//   {"name", "format": "myData", "file": path (relative to cases.jsonl), "list": the .bsxm to
//    import into (relative to cases.jsonl; in.bsxm if not given),
//    "display": "clements"|"avilist", "onlyNewDates": true|false (the "import only the new
//    dates?" question; default true), "taxa": {taxon key: base taxon ID} (as chosen while
//    resolving taxa; others are dropped), "duplicates": "importAll"|"drop"|"overwrite"}
// and is written to outDir/<name>.bsxm, with outDir/<name>.json: the counts the importer
// reports, the taxa left to resolve, the "sp."s to resolve, and how many sightings the
// duplicate check flagged. A case the importer refuses is written as outDir/<name>.error.
// The list is loaded afresh for each case, as the desktop app loads it (ReportSetLoader, then
// FrameRegistry): parse, one-time upgraders, versioned upgraders, predefined-location
// population.
// Compiled into Scythebill's imports package (it uses package-private classes); see run.sh.
package com.scythebill.birdlist.ui.imports;

import com.google.common.base.Charsets;
import com.google.common.base.Strings;
import com.google.common.collect.HashMultimap;
import com.google.common.collect.ImmutableList;
import com.google.common.collect.ImmutableSet;
import com.google.common.collect.Multimap;
import com.google.common.hash.BloomFilter;
import com.google.common.hash.Funnel;
import com.google.common.hash.PrimitiveSink;
import com.google.common.io.Files;
import com.google.gson.Gson;
import com.google.gson.JsonArray;
import com.google.gson.JsonObject;
import com.google.gson.JsonParser;
import com.google.inject.AbstractModule;
import com.google.inject.Guice;
import com.google.inject.Injector;
import com.google.inject.Provides;
import com.google.inject.Singleton;
import com.scythebill.birdlist.model.checklist.Checklists;
import com.scythebill.birdlist.model.date.PartialDate;
import com.scythebill.birdlist.model.date.PartialDateIO;
import com.scythebill.birdlist.model.date.PartialField;
import com.scythebill.birdlist.model.sighting.PredefinedLocationPopulator;
import com.scythebill.birdlist.model.sighting.PredefinedLocations;
import com.scythebill.birdlist.model.sighting.ReportSet;
import com.scythebill.birdlist.model.sighting.Sighting;
import com.scythebill.birdlist.model.sighting.SightingTaxon;
import com.scythebill.birdlist.model.sighting.SightingTaxons;
import com.scythebill.birdlist.model.sighting.VisitInfo;
import com.scythebill.birdlist.model.sighting.VisitInfoKey;
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
import kotlinx.datetime.LocalTime;
import java.util.*;
import java.util.function.Function;
import java.util.regex.*;

public class ImportOracle {
  static Taxonomy clements;
  static MappedTaxonomy avilist;
  static Injector injector;
  static Checklists checklists;
  static TaxonomyMappings mappings;

  public static void main(String[] args) throws Exception {
    Locale.setDefault(Locale.US);
    com.scythebill.birdlist.model.sighting.LocationDisplayNames.INSTANCE.setProvider(
        com.scythebill.birdlist.model.sighting.ResourceBundleLocationDisplayNames.INSTANCE);
    try (Reader r = reader(args[0])) {
      clements = new XmlTaxonImport().importTaxa(r);
    }
    try (Reader r = reader(args[1])) {
      avilist = new XmlTaxonImport().importMappedTaxa(r, clements);
    }
    injector = Guice.createInjector(new UpgraderModule(), new AbstractModule() {
      @Provides @Singleton PredefinedLocations predefinedLocations() {
        return PredefinedLocations.loadAndParse();
      }
    });
    checklists = injector.getInstance(Checklists.class);
    mappings = new TaxonomyMappings(loaders(Paths.get(args[2])), checklists);
    Path cases = Paths.get(args[4]);
    File outDir = new File(args[5]);
    outDir.mkdirs();
    for (String line : java.nio.file.Files.readAllLines(cases, StandardCharsets.UTF_8)) {
      if (line.isBlank()) continue;
      JsonObject testCase = JsonParser.parseString(line).getAsJsonObject();
      String name = testCase.get("name").getAsString();
      ReportSet reportSet = load(testCase.has("list")
          ? cases.getParent().resolve(testCase.get("list").getAsString()).toString() : args[3]);
      JsonObject summary = new JsonObject();
      try {
        runCase(reportSet, testCase, cases.getParent(), summary);
      } catch (Exception e) {
        try (Writer w = new OutputStreamWriter(
            new FileOutputStream(new File(outDir, name + ".error")), StandardCharsets.UTF_8)) {
          w.write(e.toString() + "\n");
        }
        System.out.println(name + ": " + e);
        continue;
      }
      try (Writer w = new OutputStreamWriter(
          new FileOutputStream(new File(outDir, name + ".bsxm")), StandardCharsets.UTF_8)) {
        new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
      }
      try (Writer w = new OutputStreamWriter(
          new FileOutputStream(new File(outDir, name + ".json")), StandardCharsets.UTF_8)) {
        w.write(new Gson().toJson(summary) + "\n");
      }
      System.out.println(name + ": " + summary);
    }
  }

  static ReportSet load(String path) throws Exception {
    ReportSet reportSet;
    try (BufferedReader r = new BufferedReader(reader(path))) {
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
    return reportSet;
  }

  static void runCase(ReportSet reportSet, JsonObject testCase, Path base, JsonObject summary)
      throws Exception {
    Taxonomy taxonomy = testCase.has("display")
        && testCase.get("display").getAsString().equals("avilist") ? avilist : clements;
    File file = base.resolve(testCase.get("file").getAsString()).toFile();
    PredefinedLocations predefined = injector.getInstance(PredefinedLocations.class);
    SightingsImporter<?> importer = switch (testCase.get("format").getAsString()) {
      case "myData" -> new EBirdMyDataImporter(reportSet, taxonomy, checklists, predefined, file);
      default -> throw new IllegalArgumentException(testCase.get("format").getAsString());
    };

    // ImportController.beginImport
    Optional<String> initialCheck = Optional.ofNullable(importer.initialCheck().orNull());
    if (initialCheck.isPresent()) {
      throw new IllegalStateException("initialCheck: " + initialCheck.get());
    }
    if (importer.isMassExport()) {
      PartialDate nullDate = PartialDateIO.fromString(
          "1900-01-01");
      Set<PartialDate> existingDates = new LinkedHashSet<>();
      for (Sighting s : reportSet.getSightings(importer.getTaxonomy())) {
        if (s.getLocationId() != null
            && reportSet.getLocations().getLocation(s.getLocationId()).isPrivate()) {
          continue;
        }
        PartialDate date = s.getStoredDateAsPartial();
        existingDates.add(date == null ? nullDate : date);
      }
      ImportController.NewDates newDates =
          ImportController.computeNewDates(existingDates, importer.getAllDates());
      int after = newDates.newDates().size();
      int before = newDates.countBeforeRemovingExisting();
      summary.addProperty("newDates", after);
      summary.addProperty("datesInFile", before);
      if (after > 0 && after < before) {
        boolean onlyNew = !testCase.has("onlyNewDates")
            || testCase.get("onlyNewDates").getAsBoolean();
        if (onlyNew) {
          importer.onlyImportDatesIn(newDates.newDates());
        }
      }
    }

    // parseLocationsAndTaxa
    importer.beforeParseTaxonomyIds();
    Set<String> locationsBefore = ImportCleanup.snapshotLocationIds(reportSet);
    Set<String> tripsBefore = ImportCleanup.snapshotTripIds(reportSet);
    ParsedLocationIds parsedLocationIds = importer.parseLocationIds();
    Map<Object, TaxonImporter.TbdTaxon> allTbd = importer.parseTaxonomyIds();

    // resolveImportedTaxa (without offering other languages' names)
    JsonArray tbdOut = new JsonArray();
    Set<Object> ignored = new LinkedHashSet<>();
    JsonObject chosen = testCase.has("taxa") ? testCase.getAsJsonObject("taxa") : new JsonObject();
    for (Map.Entry<Object, TaxonImporter.TbdTaxon> entry : allTbd.entrySet()) {
      TaxonImporter.TbdTaxon tbd = entry.getValue();
      if (tbd.shouldIgnore()) {
        ignored.add(entry.getKey());
        continue;
      }
      if (Strings.isNullOrEmpty(tbd.commonName) && Strings.isNullOrEmpty(tbd.scientificName)) {
        continue;
      }
      tbdOut.add(String.valueOf(entry.getKey()));
      String key = String.valueOf(entry.getKey());
      if (chosen.has(key)) {
        importer.registerTaxon(entry.getKey(), new TaxonPossibilities(
            SightingTaxons.newSightingTaxon(chosen.get(key).getAsString()), true));
      }
    }
    importer.setIgnoredTaxonIds(ignored);
    summary.add("taxaToResolve", tbdOut);
    summary.addProperty("resolvedTaxa", importer.successfullyResolvedTaxa());

    // resolveImportedLocations
    if (!parsedLocationIds.toBeResolvedNames().isEmpty()) {
      throw new IllegalStateException("locations to resolve: "
          + parsedLocationIds.toBeResolvedNames().keySet());
    }

    // parseSightings
    List<Sighting> imports = importer.parseSightings();
    summary.addProperty("sightingsFound", importer.getSightingsFoundCount());
    summary.addProperty("failed", importer.getFailedSightingsCount());
    summary.addProperty("merged", importer.getSightingsMergedCount());
    summary.addProperty("spuhsDropped", importer.getSightingsEBirdSpuhsDroppedCount());
    summary.addProperty("imported", imports.size());
    if (imports.isEmpty()) {
      throw new IllegalStateException("empty import");
    }
    if (reportSet.getUserSet() != null) {
      throw new IllegalStateException("lists with observers aren't covered");
    }

    // checkDuplicatesWithoutUsers
    int countDuplicates = countDuplicates(reportSet, imports);
    summary.addProperty("duplicatesFlagged", countDuplicates);
    String duplicates = testCase.has("duplicates")
        ? testCase.get("duplicates").getAsString() : "importAll";
    List<Sighting> toRemove = ImmutableList.of();
    if (countDuplicates > 0 && countDuplicates > (2 * (imports.size() * 0.0001))) {
      switch (duplicates) {
        case "drop" -> {
          if (countDuplicates != imports.size()) {
            imports = dropDuplicates(reportSet, importer.getTaxonomy(), imports);
          }
        }
        case "overwrite" -> toRemove = findExistingDuplicates(reportSet, imports);
        case "importAll" -> {}
        default -> throw new IllegalArgumentException(duplicates);
      }
    }
    summary.addProperty("removed", toRemove.size());
    summary.addProperty("added", imports.size());

    // finishImport
    reportSet.mutator().adding(imports).removing(toRemove).mutate();
    for (Map.Entry<VisitInfoKey, VisitInfo> entry
        : importer.getAccumulatedVisitInfoMap().entrySet()) {
      VisitInfoKey key = entry.getKey();
      VisitInfo visitInfo = entry.getValue();
      if (key.startTime() == null && visitInfo.observationType().getRequiredFields()
          .contains(VisitInfo.VisitField.START_TIME)) {
        visitInfo = visitInfo.asBuilder()
            .withObservationType(VisitInfo.ObservationType.HISTORICAL).build();
      }
      reportSet.putVisitInfo(key, visitInfo);
    }
    ImportCleanup.cleanUnneededLocationsAndTrips(reportSet, locationsBefore, tripsBefore);
    JsonArray sps = new JsonArray();
    for (SightingTaxon taxon : importer.getSpToResolve()) {
      if (!(taxonomy instanceof MappedTaxonomy)
          || taxon.resolve(taxonomy).getType() == SightingTaxon.Type.SP) {
        sps.add(String.join("/", taxon.getIds()));
      }
    }
    summary.add("spToResolve", sps);
  }

  // ImportController.SightingFunnel, countDuplicates, dropDuplicates, findExistingDuplicates
  enum SightingFunnel implements Funnel<Sighting> {
    INSTANCE;

    @Override
    public void funnel(Sighting from, PrimitiveSink into) {
      PartialDate dateAsPartial = from.getStartDateAsPartial();
      if (dateAsPartial != null) {
        field(dateAsPartial, PartialField.DAY, into);
        field(dateAsPartial, PartialField.MONTH, into);
        field(dateAsPartial, PartialField.YEAR, into);
      } else {
        into.putInt(-1);
        into.putInt(-1);
        into.putInt(-1);
      }
      LocalTime time = from.getStoredTimeAsPartial();
      if (time != null) {
        into.putInt(time.getHour());
        into.putInt(time.getMinute());
      } else {
        into.putInt(-1);
        into.putInt(-1);
      }
      into.putUnencodedChars(from.getTaxonomy().getId());
      into.putInt(from.getTaxon().getType().ordinal());
      for (String id : from.getTaxon().getIds()) {
        into.putUnencodedChars(id);
      }
    }

    private static void field(PartialDate partial, PartialField field,
        PrimitiveSink into) {
      into.putInt(partial.isSupported(field) ? partial.get(field) : -1);
    }
  }

  static int countDuplicates(ReportSet reportSet, List<Sighting> imports) {
    if (reportSet.getSightings().isEmpty()) {
      return 0;
    }
    BloomFilter<Sighting> filter = BloomFilter.create(
        SightingFunnel.INSTANCE, reportSet.getSightings().size() + imports.size(), 0.0001);
    for (Sighting sighting : reportSet.getSightings()) {
      filter.put(sighting);
    }
    int count = 0;
    for (Sighting imported : imports) {
      if (filter.mightContain(imported)) {
        count++;
      }
    }
    return count;
  }

  static List<Sighting> dropDuplicates(
      ReportSet reportSet, Taxonomy taxonomy, List<Sighting> imports) {
    Function<Sighting, ImportController.DuplicateSightingKey> key =
        ImportController.DuplicateSightingKey::forSighting;
    Set<ImportController.DuplicateSightingKey> importedKeys = new HashSet<>();
    for (Sighting imported : imports) {
      ImportController.DuplicateSightingKey k = key.apply(imported);
      if (k != null) {
        importedKeys.add(k);
      }
    }
    Function<SightingTaxon, SightingTaxon> taxonMapper = taxonomy instanceof MappedTaxonomy
        ? taxon -> taxon.resolve(taxonomy).getSightingTaxon() : Function.identity();
    Multimap<ImportController.DuplicateSightingKey, SightingTaxon> existing =
        HashMultimap.create();
    for (Sighting sighting : reportSet.getSightings(taxonomy)) {
      ImportController.DuplicateSightingKey k = key.apply(sighting);
      if (k != null && importedKeys.contains(k)) {
        existing.put(k, taxonMapper.apply(sighting.getTaxon()));
      }
    }
    List<Sighting> kept = new ArrayList<>();
    for (Sighting imported : imports) {
      ImportController.DuplicateSightingKey k = key.apply(imported);
      if (k == null || !existing.containsEntry(k, taxonMapper.apply(imported.getTaxon()))) {
        kept.add(imported);
      }
    }
    return kept;
  }

  static List<Sighting> findExistingDuplicates(ReportSet reportSet, List<Sighting> imports) {
    Multimap<ImportController.DuplicateSightingKey, SightingTaxon> imported =
        HashMultimap.create();
    for (Sighting sighting : imports) {
      ImportController.DuplicateSightingKey k =
          ImportController.DuplicateSightingKey.forSighting(sighting);
      if (k != null) {
        imported.put(k, sighting.getTaxon());
      }
    }
    List<Sighting> existing = new ArrayList<>();
    for (Sighting sighting : reportSet.getSightings()) {
      ImportController.DuplicateSightingKey k =
          ImportController.DuplicateSightingKey.forSighting(sighting);
      if (imported.containsEntry(k, sighting.getTaxon())) {
        existing.add(sighting);
      }
    }
    return existing;
  }

  static Reader reader(String path) throws IOException {
    return new InputStreamReader(new FileInputStream(path), StandardCharsets.UTF_8);
  }

  /** The TaxonomyMappingLoaders that ApplicationModule registers. */
  static Set<TaxonomyMappingLoader> loaders(Path appResources) throws IOException {
    Path module = appResources.resolve(
        "../java/com/scythebill/birdlist/app/ApplicationModule.java").normalize();
    String source = java.nio.file.Files.readString(module);
    Pattern loader = Pattern.compile(
        "new\\s+TaxonomyMappingLoader\\(\\s*\"([^\"]+)\"\\s*,\\s*Resources\\.asCharSource\\("
            + "\\s*Resources\\.getResource\\(\\s*\"([^\"]+)\"\\s*\\)"
            + "(?:[^;]*?Resources\\.getResource\\(\\s*\"([^\"]+)\"\\s*\\))?[^;]*;",
        Pattern.DOTALL);
    Matcher m = loader.matcher(source);
    Set<TaxonomyMappingLoader> result = new HashSet<>();
    while (m.find()) {
      File main = appResources.resolve(m.group(2)).toFile();
      File ssp = m.group(3) == null ? null : appResources.resolve(m.group(3)).toFile();
      result.add(new TaxonomyMappingLoader(m.group(1), Files.asCharSource(main, Charsets.UTF_8),
          ssp == null ? null : Files.asCharSource(ssp, Charsets.UTF_8)));
    }
    return result;
  }
}
