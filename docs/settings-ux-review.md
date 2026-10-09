# Profile wyszukiwania i ustawienia — analiza i zmiany

Data: 2026-10-09. Zakres: formularz profili, wszystkie zakładki ustawień, zapis konfiguracji i jej wykorzystanie przez filtry oraz scrapery.

## Znalezione problemy i poprawki

| Problem | Wdrożona zmiana |
| --- | --- |
| Osiem zakładek wymagało przewijania poziomego na komputerze. | Stała nawigacja boczna na komputerze; przewijane zakładki na wąskich ekranach. |
| Długi formularz bez czytelnych grup. | Sekcje: profil, lokalizacja, budżet i powierzchnia, standard, bezpieczeństwo, dodatkowe kryteria. |
| Niejasny zakres ustawień. | Opisy rozróżniają ustawienia jednego profilu i całej aplikacji; zapis obejmuje wszystkie szkice. |
| Zamykanie mogło pozostawić zmiany w obiektach konfiguracji. | Osobne kopie konfiguracji, status zmian, potwierdzenie odrzucenia, ostrzeżenie przed zamknięciem karty. |
| Nieaktywne zakładki nie były walidowane. | Sprawdzane są wszystkie zakładki; pomijane są pola zależne od wyłączonych funkcji i innych typów nieruchomości. |
| Złe zakresy i nieprawidłowe wartości przechodziły bez informacji. | Błędy przy polach, sprawdzanie kolejności od/do, liczb całkowitych, godzin i współrzędnych; walidacja profili w API. |
| Promień 0 km stawał się 15 km. | Wartość 0 zachowana w formularzu i adresach portali. |
| Puste maksimum ceny stawało się 1,3 mln zł; zerowe stawki znikały. | Brak limitu zapisywany jako null; wartość 0 zachowana. |
| Profile mieszkań i działek dziedziczyły metraż domu. | Osobne pola i szkice typu; nowe profile backendu nie dziedziczą ograniczeń metrażu domu. |
| Rok budowy mieszkania był pokazany, ale ignorowany. | Filtr roku budowy obsługuje również mieszkania. |
| Opóźnienie zapytań było martwym ustawieniem. | Osobne zapisane opóźnienia portali, używane przez scrapery z zachowaniem adaptacyjnego ograniczania ruchu. |
| Usuwanie bazy było stale obok zapisu i miało ukryty zakres. | Sekcja zarządzania danymi z jawnym wyborem zakresu i potwierdzeniem RESET. |
| Usuwanie niezapisanego profilu wywoływało API. | Usunięcie szkicu jest lokalne; zapisane profile mają wyraźne ostrzeżenie o natychmiastowej utracie ofert. |
| Powtórne kliknięcie mogło uruchomić drugi zapis. | Blokada równoległego zapisu, stan zajętości i informacja o błędzie. |
| Brak pełnej obsługi klawiatury. | Semantyka zakładek, strzałki/Home/End, ograniczenie fokusu do ustawień, Ctrl/Cmd+S, przyciski sugestii miast. |

## Weryfikacja i ograniczenia

Testy regresji obejmują promień 0, nieograniczony budżet, walidację profili/API, opóźnienia, rok budowy mieszkania, zachowanie szkicu i odrzucenie zmian oraz walidację zakładek w kodzie JavaScript.

Interfejs przeanalizowano z szablonu HTML, CSS i JavaScript. Narzędzie przeglądarki nie udostępniło żadnej przeglądarki ani aplikacji, dlatego wygląd na rzeczywistym ekranie i interakcje dotykowe wymagają jeszcze sprawdzenia w przeglądarce. Mechaniczny detektor wskazuje również zastane problemy całego dashboardu, m.in. twardo zapisane kolory i drobne teksty poza przebudowaną częścią.

Usunięcie zapisanego profilu i ofert nadal działa natychmiast po osobnym potwierdzeniu. Odrzucenie zmian formularza nie cofa usuwania danych. Minimum 200 m² działki przy domu pozostaje regułą domenową. Promień 0 stosowany jest w zapytaniach portali; filtr odległości nie wyznacza granic administracyjnych miasta.
