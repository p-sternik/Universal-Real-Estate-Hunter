from bs4 import BeautifulSoup

from src.scrapers.morizon import MorizonScraper


def test_morizon_parse_card():
    scraper = MorizonScraper()

    sample_html = """
    <div class="card card--bottom-margin card--box-shadow card--border" data-cy="card">
     <div class="card__outer">
      <a class="property-card__link" href="/oferta/sprzedaz-dom-rzeszow-slocina-135m2-mzn2047006905">
       Dom premium w bliźniaku 135 m² 1 350 000 zł Słocina, Rzeszów, podkarpackie
      </a>
      <a class="property-card property-card--not-highlighted" data-cy="propertyUrl" href="/oferta/sprzedaz-dom-rzeszow-slocina-135m2-mzn2047006905" rel="nofollow">
       <div class="property-card__image">
        <div>
         <div class="card-gallery">
          <div class="gallery-slider">
           <div>
            <div class="slider">
             <div class="slider__scroll">
              <ul class="slider__items">
               <li>
                <div class="gallery-slider__img-wrapper">
                 <img alt="Dom na sprzedaż" class="gallery-slider__img" data-cy="gallerySliderImgThumbnail" src="https://img1.staticmorizon.com.pl/thumb/test/dom.jpg"/>
                </div>
               </li>
              </ul>
             </div>
            </div>
           </div>
          </div>
         </div>
        </div>
       </div>
       <div class="property-card__property-details">
        <div class="property-card__header">
         <div class="property-card__title" data-cy="propertyCardTitle">
          Dom premium w bliźniaku Twój wymarzony dom!
         </div>
         <div class="property-card__location" data-cy="propertyCardLocation">
          <span>Księdza Sulikowskiego, Słocina, Rzeszów, podkarpackie</span>
         </div>
        </div>
        <div class="property-card__price" data-cy="cardPropertyOfferPrice">
         <div class="property-card__price--wrapper">
          <span class="property-card__price--main" data-cy="propertyCardPrice">
           1 350 000 zł
          </span>
          <span class="property-card__price--perM2" data-cy="offerPricePerM2">
           10 000 zł/m²
          </span>
         </div>
        </div>
        <div class="property-card__info">
         <div class="offer-info">
          <span data-cy="cardPropertyInfoArea">
           135 m²
          </span>
          <span class="offer-info__separator">•</span>
          <span data-cy="cardPropertyInfoRooms">
           4 pokoje
          </span>
         </div>
        </div>
        <div class="property-card__property-description">
         <div class="description">
          <div class="show-more description__show-more">
           <div class="show-more__body">
            <div class="show-more__content">
             <div class="description__content">
              <span class="description__advertisement-text">Dom premium w bliźniaku</span>
              <div>Opis Oferta bezpośrednia Dom premium w bliźniaku. Ogród 2,5 ara.</div>
             </div>
            </div>
           </div>
          </div>
         </div>
        </div>
       </div>
      </a>
     </div>
    </div>
    """

    soup = BeautifulSoup(sample_html, "html.parser")
    card = soup.select_one("div.card")
    listing = scraper._parse_card(card)

    assert listing is not None
    assert listing.portal == "Morizon"
    assert listing.id == "mzn2047006905"
    assert listing.price == 1_350_000.0
    assert listing.price_per_m2 == 10_000.0
    assert listing.area_home == 135.0
    assert listing.rooms == 4
    assert "Słocina" in listing.location_raw
    assert listing.street == "Księdza Sulikowskiego"
    assert listing.main_image_url == "https://img1.staticmorizon.com.pl/thumb/test/dom.jpg"
    assert "morizon.pl" in listing.url
    assert listing.is_private_owner is True  # "Oferta bezpośrednia" in description
    assert listing.area_plot == 250.0  # "2,5 ara" -> 250 m²


def test_morizon_parse_card_no_offer_link():
    """Cards without /oferta/ link should be skipped."""
    scraper = MorizonScraper()

    sample_html = """
    <div class="card card--bottom-margin card--box-shadow">
     <div class="card__outer">
      <a class="property-card__link" href="/mieszkania/rzeszow/">
       Mieszkania w Rzeszowie
      </a>
     </div>
    </div>
    """

    soup = BeautifulSoup(sample_html, "html.parser")
    card = soup.select_one("div.card")
    listing = scraper._parse_card(card)
    assert listing is None


def test_morizon_url_builder():
    from src.services.config_manager import SearchProfile

    profile = SearchProfile(
        city="Rzeszów",
        category="dom",
        min_price=300_000,
        max_price=1_200_000,
        min_area_home=100,
        max_area_home=150,
    )
    url = profile.get_morizon_url()
    assert "morizon.pl/domy/rzeszow/" in url
    assert "ps%5Bprice_from%5D=300000" in url
    assert "ps%5Bprice_to%5D=1200000" in url
    assert "ps%5Bliving_area_from%5D=100" in url
    assert "ps%5Bliving_area_to%5D=150" in url


def test_morizon_url_builder_dzialka():
    from src.services.config_manager import SearchProfile

    profile = SearchProfile(
        city="Rzeszów",
        category="dzialka",
        min_price=50_000,
        max_price=500_000,
        min_area_plot=1000,
        max_area_plot=5000,
    )
    url = profile.get_morizon_url()
    assert "morizon.pl/dzialki/rzeszow/" in url
    assert "ps%5Bprice_from%5D=50000" in url
    assert "ps%5Bliving_area_from%5D=1000" in url


def test_morizon_url_builder_mieszkanie():
    from src.services.config_manager import SearchProfile

    profile = SearchProfile(
        city="Rzeszów",
        category="mieszkanie",
        min_price=200_000,
        max_price=600_000,
        min_area_home=40,
        max_area_home=80,
    )
    url = profile.get_morizon_url()
    assert "morizon.pl/mieszkania/rzeszow/" in url
