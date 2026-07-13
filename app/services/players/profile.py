from dataclasses import dataclass

from app.services.base import TransfermarktBase
from app.utils.regex import REGEX_DOB_AGE
from app.utils.utils import extract_from_url, safe_regex, trim
from app.utils.xpath import Players


@dataclass
class TransfermarktPlayerProfile(TransfermarktBase):
    """
    Represents a service for retrieving and parsing the profile information of a football player on Transfermarkt.

    Args:
        player_id (str): The unique identifier of the player.

    Attributes:
        URL (str): The URL to fetch the player's profile data.
    """

    player_id: str = None
    URL: str = "https://www.transfermarkt.com/-/profil/spieler/{player_id}"
    FALLBACK_URL: str = "https://www.transfermarkt.es/-/profil/spieler/{player_id}"

    def __post_init__(self) -> None:
        """Initialize the TransfermarktPlayerProfile class."""
        self.URL = self.URL.format(player_id=self.player_id)
        self.FALLBACK_URL = self.FALLBACK_URL.format(player_id=self.player_id)
        self.page = self.__fetch_player_page()
        self.raise_exception_if_not_found(xpath=Players.Profile.URL)

    def __fetch_player_page(self):
        """
        Fetch the player profile page, trying multiple domain mirrors for better reliability.
        Falls back to .es domain if .com fails with 502/504 errors.

        Returns:
            ElementTree: The parsed player profile page.

        Raises:
            HTTPException: If all URLs fail.
        """
        from fastapi import HTTPException
        
        last_error = None
        
        for idx, url in enumerate((self.URL, self.FALLBACK_URL), 1):
            try:
                print(f"[Profile] Attempt {idx}/2: Fetching from {url}")
                # Temporarily override URL for request
                original_url = self.URL
                self.URL = url
                page = self.request_url_page()
                self.URL = original_url  # Restore original
                print(f"[Profile] Success on attempt {idx}")
                return page
            except HTTPException as error:
                last_error = error
                print(f"[Profile] Attempt {idx} failed with {error.status_code}: {error.detail}")
                # Only retry on server errors (502, 504, etc.)
                if error.status_code >= 500:
                    continue
                # For client errors (404, etc.), fail immediately
                raise
            except Exception as error:
                last_error = HTTPException(status_code=500, detail=f"Error fetching player page: {str(error)}")
                print(f"[Profile] Attempt {idx} exception: {str(error)}")
                continue
        
        # All attempts failed
        print(f"[Profile] All attempts failed for player {self.player_id}")
        raise last_error if last_error else HTTPException(status_code=500, detail="Failed to fetch player page")

    def __parse_player_relatives(self) -> list:
        """
        Parse the list of related players or trainers from the 'Further information' section on the player page
        Returns:
            list: A list of dictionaries, each containing ID, profile URL, name, and profile type
        """
        relatives = self.page.xpath(Players.Profile.RELATIVES)

        result = []
        for relative in relatives:
            url = trim(relative.xpath(Players.Profile.RELATIVE_URL))
            name = trim(relative.xpath(Players.Profile.RELATIVE_NAME))
            result.append(
                {
                    "id": extract_from_url(url),
                    "url": url,
                    "name": name,
                    "profileType": "player" if "spieler" in url else "trainer",
                },
            )

        return result

    def get_player_profile(self) -> dict:
        """
        Retrieve and parse the player's profile information, including their personal details,
        club affiliations, market value, agent information, social media links, and more.

        Returns:
            dict: A dictionary containing the player's unique identifier, profile information, and the timestamp of when
                the data was last updated.
        """
        self.response["id"] = self.get_text_by_xpath(Players.Profile.ID)
        self.response["url"] = self.get_text_by_xpath(Players.Profile.URL)
        self.response["name"] = self.get_text_by_xpath(Players.Profile.NAME, join_str=" ")
        self.response["description"] = self.get_text_by_xpath(Players.Profile.DESCRIPTION)
        self.response["fullName"] = self.get_text_by_xpath(Players.Profile.FULL_NAME)
        self.response["nameInHomeCountry"] = self.get_text_by_xpath(Players.Profile.NAME_IN_HOME_COUNTRY)
        self.response["imageUrl"] = self.get_text_by_xpath(Players.Profile.IMAGE_URL)
        dob_cell = self.get_text_by_xpath(Players.Profile.DATE_OF_BIRTH)
        if dob_cell and dob_cell.strip():
            self.response["dateOfBirth"] = dob_cell.strip()
        else:
            # Fallback to parsing the 'birthDate/age' span with regex
            self.response["dateOfBirth"] = safe_regex(
                self.get_text_by_xpath(Players.Profile.DATE_OF_BIRTH_AGE),
                REGEX_DOB_AGE,
                "dob",
            )
        # Optional: remove this testing field or keep it only in tests
        # self.response["dateOfBirthTest"] = dob_cell
        self.response["dateOfBirthTest"] = self.get_text_by_xpath(Players.Profile.DATE_OF_BIRTH)
        self.response["placeOfBirth"] = {
            "city": self.get_text_by_xpath(Players.Profile.PLACE_OF_BIRTH_CITY),
            "country": self.get_text_by_xpath(Players.Profile.PLACE_OF_BIRTH_COUNTRY),
        }
        self.response["age"] = safe_regex(
            self.get_text_by_xpath(Players.Profile.DATE_OF_BIRTH_AGE),
            REGEX_DOB_AGE,
            "age",
        )
        self.response["height"] = self.get_text_by_xpath(Players.Profile.HEIGHT)
        self.response["citizenship"] = self.get_list_by_xpath(Players.Profile.CITIZENSHIP)
        self.response["isRetired"] = self.get_text_by_xpath(Players.Profile.RETIRED_SINCE_DATE) is not None
        self.response["retiredSince"] = self.get_text_by_xpath(Players.Profile.RETIRED_SINCE_DATE)
        self.response["position"] = {
            "main": self.get_text_by_xpath(Players.Profile.POSITION_MAIN),
            "other": self.get_list_by_xpath(Players.Profile.POSITION_OTHER),
        }
        self.response["foot"] = self.get_text_by_xpath(Players.Profile.FOOT)
        self.response["shirtNumber"] = self.get_text_by_xpath(Players.Profile.SHIRT_NUMBER)
        self.response["club"] = {
            "id": extract_from_url(self.get_text_by_xpath(Players.Profile.CURRENT_CLUB_URL)),
            "name": self.get_text_by_xpath(Players.Profile.CURRENT_CLUB_NAME),
            "joined": self.get_text_by_xpath(Players.Profile.CURRENT_CLUB_JOINED),
            "contractExpires": self.get_text_by_xpath(Players.Profile.CURRENT_CLUB_CONTRACT_EXPIRES),
            "contractOption": self.get_text_by_xpath(Players.Profile.CURRENT_CLUB_CONTRACT_OPTION),
            "lastClubId": extract_from_url(self.get_text_by_xpath(Players.Profile.LAST_CLUB_URL)),
            "lastClubName": self.get_text_by_xpath(Players.Profile.LAST_CLUB_NAME),
            "mostGamesFor": self.get_text_by_xpath(Players.Profile.MOST_GAMES_FOR_CLUB_NAME),
        }
        raw_market_value = self.get_text_by_xpath(Players.Profile.MARKET_VALUE, iloc_to=3, join_str="")
        # Clean up market value by removing "Última revisión" or "Last update" text
        if raw_market_value:
            # Split by common separators and take only the first part (the actual value)
            market_value_clean = raw_market_value.split("Última")[0].split("Last")[0].strip()
            self.response["marketValue"] = market_value_clean
        else:
            self.response["marketValue"] = raw_market_value
        self.response["agent"] = {
            "name": self.get_text_by_xpath(Players.Profile.AGENT_NAME),
            "url": self.get_text_by_xpath(Players.Profile.AGENT_URL),
        }
        self.response["outfitter"] = self.get_text_by_xpath(Players.Profile.OUTFITTER)
        self.response["socialMedia"] = self.get_list_by_xpath(Players.Profile.SOCIAL_MEDIA)
        self.response["trainerProfile"] = {
            "id": extract_from_url(self.get_text_by_xpath(Players.Profile.TRAINER_PROFILE_URL)),
            "url": self.get_text_by_xpath(Players.Profile.TRAINER_PROFILE_URL),
            "position": self.get_text_by_xpath(Players.Profile.TRAINER_PROFILE_POSITION),
        }
        self.response["relatives"] = self.__parse_player_relatives()

        return self.response
