import Foundation

/// Lokalisiert einen zur LAUFZEIT bekannten String, indem der String selbst als
/// Schlüssel in `Localizable.strings` (Bundle.main) nachgeschlagen wird.
///
/// Nötig für alle Strings, die als `String`-Parameter durch Views/Komponenten
/// laufen (z.B. `WizSlider(label:)`, `group(title:)`, Segmented-Optionen). SwiftUIs
/// `Text("literal")` lokalisiert NUR direkte String-Literale (über `LocalizedStringKey`),
/// nicht `String`-Variablen — die landen sonst in der verbatim-Initialisierung und
/// bleiben in der Quellsprache (Englisch) stehen.
///
/// Schlüssel = englischer Quelltext (Quellsprache). Nicht gefunden → gibt den
/// Schlüssel zurück (also Englisch), sodass nie ein leerer/kaputter Text entsteht.
///
/// Hinweis: greift nur im gebündelten `.app` (build_app.sh legt de.lproj/en.lproj
/// in Contents/Resources ab). Im `swift run`-Dev-Build fehlt der Katalog → immer
/// der englische Schlüssel. Sprachtest deshalb am gebauten App-Bundle.
func loc(_ key: String) -> String {
    NSLocalizedString(key, comment: "")
}
