// Scythebill's load-and-save of a .bsxm, as the desktop app does it, for Pipit's
// round-trip tests:
//   java -cp <cp> RoundTrip.java taxon.xml avilist.xml appResources in.bsxm out.bsxm
// Steps (ReportSetLoader.call, then FrameRegistry): parse (with taxonomy-ID upgrades),
// one-time upgraders, versioned upgraders, predefined-location population, export.
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

public class RoundTrip {
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

    try (Writer w = new OutputStreamWriter(new FileOutputStream(args[4]), StandardCharsets.UTF_8)) {
      new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
    }
    System.out.println("round trip done: " + reportSet.getSightings().size() + " sightings");
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
