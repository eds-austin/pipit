// A brand-new, empty Scythebill list, exactly as Scythebill creates one (all world regions,
// countries and US states; every one-time upgrade marked done):
//   java -cp <cp> NewList.java taxon.xml out.bsxm
import com.google.inject.AbstractModule;
import com.google.inject.Guice;
import com.google.inject.Injector;
import com.google.inject.Provides;
import com.google.inject.Singleton;
import com.scythebill.birdlist.model.sighting.PredefinedLocations;
import com.scythebill.birdlist.model.sighting.ReportSet;
import com.scythebill.birdlist.model.sighting.ReportSets;
import com.scythebill.birdlist.model.sighting.upgrades.OneTimeUpgradeProcessor;
import com.scythebill.birdlist.model.sighting.upgrades.UpgraderModule;
import com.scythebill.birdlist.model.taxa.Taxonomy;
import com.scythebill.birdlist.model.xml.XmlReportSetExport;
import com.scythebill.birdlist.model.xml.XmlTaxonImport;
import java.io.*;
import java.nio.charset.StandardCharsets;

public class NewList {
  public static void main(String[] args) throws Exception {
    Taxonomy clements;
    try (Reader r = new InputStreamReader(new FileInputStream(args[0]), StandardCharsets.UTF_8)) {
      clements = new XmlTaxonImport().importTaxa(r);
    }
    ReportSet reportSet = ReportSets.newReportSet(clements);
    Injector injector = Guice.createInjector(new UpgraderModule(), new AbstractModule() {
      @Provides @Singleton PredefinedLocations predefinedLocations() {
        return PredefinedLocations.loadAndParse();
      }
    });
    injector.getInstance(OneTimeUpgradeProcessor.class).markAllUpgraded(reportSet);
    try (Writer w = new OutputStreamWriter(new FileOutputStream(args[1]), StandardCharsets.UTF_8)) {
      new XmlReportSetExport().export(w, "UTF-8", reportSet, clements);
    }
    System.out.println("new list written");
  }
}
