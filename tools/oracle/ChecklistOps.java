// Scythebill's load of a .bsxm (as RoundTrip.java), then a custom checklist edited or
// deleted as its Locations screen does, then save:
//   java -cp <cp> ChecklistOps.java taxon.xml avilist.xml appResources in.bsxm out.bsxm \
//       DISPLAY OP...
// DISPLAY is "clements" or "avilist". "delete:LOC" is ReportSetExtensions.removeChecklist.
// "edit:LOC:CHANGE;..." is EditChecklistPanel (its table model copied below): CHANGE is
// "status=ID=TEXT" (TEXT "native" or a status text), "remove=ID" or "add=ID", with display
// taxon IDs; then OK rebuilds the map (Maps.newHashMapWithExpectedSize) and saves it.
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

public class ChecklistOps {
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

    Taxonomy display = args[5].equals("avilist") ? avilist : clements;
    for (int i = 6; i < args.length; i++) {
      String[] op = args[i].split(":", 3);
      var location = reportSet.getLocations().getLocation(op[1]);
      switch (op[0]) {
        case "delete" -> com.scythebill.birdlist.model.sighting.ReportSetExtensions
            .removeChecklist(reportSet, location);
        case "edit" -> edit(reportSet, location, display, op.length > 2 ? op[2] : "");
        default -> throw new IllegalArgumentException(args[i]);
      }
    }
    try (Writer w = new OutputStreamWriter(new FileOutputStream(args[4]), StandardCharsets.UTF_8)) {
      new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
    }
    System.out.println("round trip done: " + reportSet.getSightings().size() + " sightings");
  }

  /** EditChecklistPanel.TableRow. */
  record Row(com.scythebill.birdlist.model.sighting.SightingTaxon taxon,
      com.scythebill.birdlist.model.sighting.SightingTaxon.Resolved resolved,
      com.scythebill.birdlist.model.checklist.Checklist.Status[] status) {}

  /** EditChecklistPanel: its ChecklistTableModel, edits, and the OK button. */
  static void edit(ReportSet reportSet, com.scythebill.birdlist.model.sighting.Location location,
      Taxonomy taxonomy, String changes) {
    var checklist = (com.scythebill.birdlist.model.checklist.ClementsChecklist)
        com.scythebill.birdlist.model.sighting.ReportSetExtensions.getChecklist(reportSet, location);
    Map<com.scythebill.birdlist.model.sighting.SightingTaxon,
        com.scythebill.birdlist.model.checklist.Checklist.Status> checklistMap =
        com.google.common.collect.Maps.newHashMap(checklist.baseChecklistMap());
    var comparator = new com.scythebill.birdlist.model.util.ResolvedComparator();
    List<Row> list = new ArrayList<>();
    for (var entry : checklistMap.entrySet()) {
      list.add(new Row(entry.getKey(), entry.getKey().resolve(taxonomy),
          new com.scythebill.birdlist.model.checklist.Checklist.Status[] {entry.getValue()}));
    }
    Comparator<Row> byResolved = (a, b) -> comparator.compare(a.resolved(), b.resolved());
    Collections.sort(list, byResolved);
    for (String change : changes.isEmpty() ? new String[0] : changes.split(";")) {
      String[] parts = change.split("=", 3);
      switch (parts[0]) {
        case "status" -> {
          var status = parts[2].equals("native")
              ? com.scythebill.birdlist.model.checklist.Checklist.Status.NATIVE
              : com.scythebill.birdlist.model.checklist.Checklist.Status.valueOf(
                  parts[2].toUpperCase(Locale.ROOT).replace('-', '_'));
          rowOf(list, parts[1]).status()[0] = status;
        }
        case "remove" -> list.remove(rowOf(list, parts[1]));
        case "add" -> {
          var resolved = com.scythebill.birdlist.model.sighting.SightingTaxons.newResolved(
              taxonomy.getTaxon(parts[1]));
          var row = new Row(resolved.getSightingTaxonInBaseTaxonomy(), resolved,
              new com.scythebill.birdlist.model.checklist.Checklist.Status[] {
                  com.scythebill.birdlist.model.checklist.Checklist.Status.NATIVE});
          int index = Collections.binarySearch(list, row, byResolved);
          if (index < 0) {
            list.add(-(index + 1), row);
          }
        }
        default -> throw new IllegalArgumentException(change);
      }
    }
    Map<com.scythebill.birdlist.model.sighting.SightingTaxon,
        com.scythebill.birdlist.model.checklist.Checklist.Status> updated =
        com.google.common.collect.Maps.newHashMapWithExpectedSize(list.size());
    for (Row row : list) {
      updated.put(row.taxon(), row.status()[0]);
    }
    com.scythebill.birdlist.model.sighting.ReportSetExtensions.setChecklist(reportSet, location,
        new com.scythebill.birdlist.model.checklist.ClementsChecklist(updated));
  }

  static Row rowOf(List<Row> list, String displayId) {
    for (Row row : list) {
      var resolved = row.resolved();
      if (resolved.getType() == com.scythebill.birdlist.model.sighting.SightingTaxon.Type.SINGLE
          && resolved.getTaxon().getId().equals(displayId)) {
        return row;
      }
    }
    throw new IllegalArgumentException("no row " + displayId);
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
