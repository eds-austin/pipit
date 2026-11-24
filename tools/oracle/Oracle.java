// Scythebill as an oracle for Pipit's M1 ports. Run with the model classpath:
//   java -cp <cp> Oracle.java taxon.xml avilist.xml corpus.txt multilingualDir outDir
import com.google.common.util.concurrent.MoreExecutors;
import com.scythebill.birdlist.model.sighting.SightingTaxon;
import com.scythebill.birdlist.model.sighting.SightingTaxons;
import com.scythebill.birdlist.model.taxa.MappedTaxonomy;
import com.scythebill.birdlist.model.taxa.Taxon;
import com.scythebill.birdlist.model.taxa.Taxonomy;
import com.scythebill.birdlist.model.taxa.names.AviListNamesLoader;
import com.scythebill.birdlist.model.taxa.names.NamesLoader;
import com.scythebill.birdlist.model.util.AlternateName;
import com.scythebill.birdlist.model.util.Indexer;
import com.scythebill.birdlist.model.util.TaxonomyIndexer;
import com.scythebill.birdlist.model.xml.XmlTaxonImport;
import com.opencsv.CSVReader;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.CompletableFuture;

public class Oracle {
  public static void main(String[] args) throws Exception {
    Path out = Paths.get(args[4]);
    Files.createDirectories(out);
    Taxonomy clements;
    try (Reader r = Files.newBufferedReader(Paths.get(args[0]), StandardCharsets.UTF_8)) {
      clements = new XmlTaxonImport().importTaxa(r);
    }
    MappedTaxonomy avilist;
    try (Reader r = Files.newBufferedReader(Paths.get(args[1]), StandardCharsets.UTF_8)) {
      avilist = new XmlTaxonImport().importMappedTaxa(r, clements);
    }
    for (Taxonomy t : List.of(clements, avilist)) {
      new TaxonomyIndexer(CompletableFuture.completedFuture(t))
          .load(MoreExecutors.newDirectExecutorService()).get();
    }

    List<String> queries = Files.readAllLines(Paths.get(args[2]), StandardCharsets.UTF_8);
    try (PrintWriter w = writer(out.resolve("search.tsv"))) {
      for (Taxonomy t : List.of(clements, avilist)) {
        for (String q : queries) {
          w.println(t.getId() + "\tcommon\t" + q + "\t" + ids(t.getCommonIndexer().find(q)));
          w.println(t.getId() + "\tscientific\t" + q + "\t" + ids(t.getScientificIndexer().find(q)));
          w.println(t.getId() + "\talternate-common\t" + q + "\t" + alts(t.getAlternateCommonIndexer().find(q)));
          w.println(t.getId() + "\talternate-scientific\t" + q + "\t" + alts(t.getAlternateScientificIndexer().find(q)));
        }
      }
    }

    try (PrintWriter w = writer(out.resolve("resolutions.tsv"))) {
      for (Taxon taxon : all(clements.getRoot())) {
        if (taxon.getParent() == null) continue;
        String line;
        try {
          SightingTaxon.Resolved r = avilist.resolveInto(SightingTaxons.newSightingTaxon(taxon.getId()));
          line = r == null ? "NONE" : kind(r.getType()) + "\t" + String.join(",", sorted(r.getSightingTaxon().getIds()));
        } catch (RuntimeException e) {
          line = "ERROR\t" + e.getClass().getSimpleName();
        }
        w.println(taxon.getId() + "\t" + line);
      }
    }

    try (PrintWriter w = writer(out.resolve("mapping_back.tsv"))) {
      for (Taxon taxon : all(avilist.getRoot())) {
        SightingTaxon m = avilist.getMapping(taxon);
        w.println(taxon.getId() + "\t" + (taxon.isDisabled() ? "disabled" : "enabled") + "\t"
            + (m == null ? "NONE" : kind(m.getType()) + "\t" + String.join(",", sorted(m.getIds()))
                + (m.getType() == SightingTaxon.Type.SINGLE_WITH_SECONDARY_SUBSPECIES ? "|" + m.getSubIdentifier() : "")));
      }
    }

    Path multilingual = Paths.get(args[3]);
    NamesLoader clementsNames = new NamesLoader() {
      @Override public Map<String, String> load(String locale) {
        Map<String, String> names = new HashMap<>();
        Path file = multilingual.resolve("clements-names-" + locale + ".csv");
        if (!Files.exists(file)) return names;
        try (CSVReader csv = new CSVReader(Files.newBufferedReader(file, StandardCharsets.UTF_8))) {
          String[] line;
          while ((line = csv.readNext()) != null) names.put(line[0], line[1]);
        } catch (Exception e) { throw new RuntimeException(e); }
        return names;
      }
      @Override public Set<String> findPresentNames(String locale, Set<String> taxonNames) { return Set.of(); }
    };
    for (String locale : List.of("de", "fr", "en_GB", "ja")) {
      Map<String, String> names = new TreeMap<>(new AviListNamesLoader(clementsNames, avilist).load(locale));
      try (PrintWriter w = writer(out.resolve("avilist_names_" + locale + ".tsv"))) {
        names.forEach((id, name) -> w.println(id + "\t" + name));
      }
    }
    System.out.println("oracle done: " + queries.size() + " queries");
  }

  static PrintWriter writer(Path p) throws IOException {
    return new PrintWriter(Files.newBufferedWriter(p, StandardCharsets.UTF_8));
  }

  static String kind(SightingTaxon.Type type) {
    return switch (type) {
      case SINGLE -> "single";
      case SP -> "sp";
      case HYBRID -> "hybrid";
      case SINGLE_WITH_SECONDARY_SUBSPECIES -> "ssp";
    };
  }

  static List<String> sorted(Collection<String> ids) {
    List<String> list = new ArrayList<>(ids);
    Collections.sort(list);
    return list;
  }

  static String ids(Collection<String> found) {
    return String.join("\u001f", sorted(found));
  }

  static String alts(Collection<AlternateName<String>> found) {
    List<String> list = new ArrayList<>();
    for (AlternateName<String> a : found) list.add(a.getName() + "|" + a.getObject());
    return String.join("\u001f", sorted(list));
  }

  static List<Taxon> all(Taxon root) {
    List<Taxon> list = new ArrayList<>();
    Deque<Taxon> stack = new ArrayDeque<>();
    stack.push(root);
    while (!stack.isEmpty()) {
      Taxon t = stack.pop();
      list.add(t);
      List<Taxon> children = new ArrayList<>(t.getContents());
      Collections.reverse(children);
      for (Taxon c : children) stack.push(c);
    }
    return list;
  }
}
