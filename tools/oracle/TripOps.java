// Scythebill's load of a .bsxm (as RoundTrip.java), then trip changes made as its Trips
// screen makes them, then save:
//   java -cp <cp> TripOps.java taxon.xml avilist.xml appResources in.bsxm out.bsxm OP...
// "delete:ID" is ReportSet.deleteTrips (as TripsBrowsePanel.deleteTrips); "edit:ID:F=V|..."
// with fields name, start, end, loc, notes is TripInfoBrowsePanel.save (copied below,
// including moving the trip's sightings at its old place to the new one).
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

public class TripOps {
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

    for (int i = 5; i < args.length; i++) {
      String[] op = args[i].split(":", 3);
      com.scythebill.birdlist.model.sighting.Trip trip = null;
      for (var candidate : reportSet.getTrips().allTrips()) {
        if (candidate.id().equals(op[1])) trip = candidate;
      }
      if (trip == null) throw new IllegalArgumentException("no trip " + op[1]);
      switch (op[0]) {
        case "delete" -> reportSet.deleteTrips(List.of(trip), null);
        case "edit" -> edit(reportSet, trip, op[2]);
        default -> throw new IllegalArgumentException(args[i]);
      }
    }
    try (Writer w = new OutputStreamWriter(new FileOutputStream(args[4]), StandardCharsets.UTF_8)) {
      new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
    }
    System.out.println("round trip done: " + reportSet.getSightings().size() + " sightings");
  }

  /** TripInfoBrowsePanel.save, with the edited values in place of its fields. */
  static void edit(ReportSet reportSet, com.scythebill.birdlist.model.sighting.Trip trip,
      String spec) {
    Map<String, String> values = new HashMap<>();
    for (String part : spec.split("\\|")) {
      String[] pair = part.split("=", 2);
      values.put(pair[0], pair[1]);
    }
    String name = values.getOrDefault("name", com.google.common.base.Strings.nullToEmpty(trip.name()));
    var start = values.containsKey("start")
        ? com.scythebill.birdlist.model.date.PartialDateIO.fromString(values.get("start"))
        : trip.startDate();
    var end = values.containsKey("end")
        ? com.scythebill.birdlist.model.date.PartialDateIO.fromString(values.get("end"))
        : trip.endDate();
    String notes = values.getOrDefault("notes", trip.notes() == null ? "" : trip.notes());
    var where = values.containsKey("loc")
        ? reportSet.getLocations().getLocation(values.get("loc"))
        : (trip.locationId() == null ? null : reportSet.getLocations().getLocation(trip.locationId()));

    // As the panel's fields: null shows (and compares) as "".
    if (!java.util.Objects.equals(com.google.common.base.Strings.nullToEmpty(trip.name()), name)) {
      trip.setName(name);
    }
    if (!java.util.Objects.equals(trip.startDate(), start)
        || !java.util.Objects.equals(trip.endDate(), end)) {
      trip.setDates(start, end);
    }
    String originalNotes = trip.notes() == null ? "" : trip.notes();
    if (!java.util.Objects.equals(originalNotes, notes)) {
      trip.setNotes(notes);
    }
    if (where != null) {
      reportSet.getLocations().ensureAdded(where);
    }
    if (!java.util.Objects.equals(trip.locationId(), where == null ? null : where.getId())) {
      if (where != null) {
        List<com.scythebill.birdlist.model.sighting.Sighting> toRemove = new ArrayList<>();
        List<com.scythebill.birdlist.model.sighting.Sighting> toAdd = new ArrayList<>();
        for (var sighting : reportSet.getSightings()) {
          if (sighting.getTrip() == trip
              && java.util.Objects.equals(sighting.getLocationId(), trip.locationId())) {
            toAdd.add(sighting.asBuilder().setLocation(where).build());
            toRemove.add(sighting);
          }
        }
        reportSet.mutator().adding(toAdd).removing(toRemove).mutate();
      }
      trip.setLocation(where);
    }
    trip.setLinks(trip.links());
    trip.setPhotos(trip.photos());
    reportSet.markDirty();
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
