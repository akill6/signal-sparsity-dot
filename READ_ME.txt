-- Pokyny na spustenie --
1. Otvorte MATLAB.
2. Otvorte súbor: number_2.mlapp
3. Kliknite na Run.

P.s. Neumiestňujte iné panely nad hlavný panel „app.Panel“, pretože aplikácia nebude fungovať, 
keďže databáza signálov sa začne načítať do aplikácie po stlačení tlačidla „Začať analýzu“ na hlavnom paneli. 
To znamená, že ak umiestnite „app.Panel_2“ nad panel „app.Panel“, aplikácia nebude fungovať. 

-- Stručný popis funkcií aplikácie --
1. Načítanie signálu:
* Po spustení aplikácie kliknite na tlačidlo Začať analýzu.
* Zo zoznamu vyberte signál (MAT súbor) zo zložky matDBs.

2. Výber transformácie:
* Používateľ si môže vybrať jednu z možností:
- DFT
- DCT
- DWT

* Pri DWT sa automaticky analyzujú wavelety:
- Haar
- db2

3. Výber metriky kvality:
* Používateľ môže zadať:
- PRD – Percent Root Difference (%)
- SNR – Signal-to-Noise Ratio (dB)

** Dôležité:
Aplikácia automaticky rozpozná, ktorú metrikou používateľ zadal naposledy, a tú použije ako prioritnú pri optimalizácii.

-- Popis hlavných funkcií aplikácie --
1. computeDFT:
* Účel:
Analýza signálu v priestore diskrétnej Fourierovej transformácie.

* Postup:
- vykoná FFT signálu,
- zachová DC zložku,
- zoradí koeficienty podľa amplitúdy,
- pomocou binárneho vyhľadávania nájde minimálny počet koeficientov,
- rekonštruuje signál,
- vypočíta metriky: PRD, SNR, sparzitu, kompresný pomer a energiu.

2. computeDCT
* Účel:
Analýza sparzity v priestore diskrétnej kosínusovej transformácie.

* Charakteristika:
- používa 1D DCT,
- DC koeficient je vždy zachovaný,
- prahovanie sa vykonáva podľa veľkosti koeficientov,
- optimalizácia prebieha podľa PRD alebo SNR.

3. computeDWT
* Účel:
Analýza signálu pomocou diskrétnej waveletovej transformácie.

* Vlastnosti:
- viacúrovňový rozklad (defaultne 5 úrovní),
- podpora viacerých waveletov (Haar, db2),
- porovnanie sparzity medzi waveletmi,
- ukladanie výsledkov oddelene pre každý wavelet.

4. SpustiButtonPushed
* Úloha:
- hlavný riadiaci bod výpočtu,
- vyhodnocuje prioritu PRD / SNR,
- volá príslušnú transformačnú funkciu,
- aktualizuje tabuľku metrík a grafy.

5. VybertetypzobrazeniaDropDownOpening
* Účel:
- zabezpečuje jednotnú a porovnateľnú vizualizáciu,
- zobrazuje:
	- pôvodný signál,
	- rekonštruovaný signál,
	- rozdiel,

- vykresľuje spektrá s:
	- potlačením DC zložky len pre vizualizáciu,
	- jednotným prahom (1 % maxima),
	- normalizáciou amplitúdy.

-- Funkcie pre PRD a SNR --
1. VybertePRDEditFieldValueChanged:
- kontrola vstupu PRD,
- nastavenie priority optimalizácie.

2. VyberteSNREditFieldValueChanged:
- kontrola vstupu SNR,
- prepnutie priority optimalizácie.

-- Výstupy aplikácie --
- Časový priebeh signálu
- Rekonštruovaný signál
- Rozdielový signál
- Spektrálne reprezentácie

* Tabuľka metrík:
- PRD
- SNR
- Sparzita
- Kompresný pomer
- Zachovaná energia

-- Poznámky k vedeckej korektnosti --
- Rovnaké pravidlá prahovania sú použité pre všetky transformácie.
- Vizualizácia neovplyvňuje numerické metriky.
- DC komponent je zachovaný vo výpočtoch, potlačený len graficky.



