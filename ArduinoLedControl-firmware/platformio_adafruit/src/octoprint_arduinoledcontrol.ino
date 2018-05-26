
#include "NeopixelPattern.h"

#define LED_STRIP_PIN 6
#define BUILTIN_LED_PIN 13
#define NUM_LEDS 30
#define BRIGHTNESS 255

#define BAUD_RATE 9600

void on_pattern_complete();


NeoPatterns strip(NUM_LEDS, LED_STRIP_PIN, NEO_GRBW + NEO_KHZ800, &on_pattern_complete);

uint32_t cool_color = strip.Color(0, 0, 255);
uint32_t hot_color = strip.Color(255, 0, 0);

void pulseWhite(uint8_t wait, unsigned int increment) {
    if (increment > 50) {
        increment = 50;
    }
    for(int j = 0; j < 256 ; j += increment){
        for(uint16_t i=0; i<strip.numPixels(); i++) {
            strip.setPixelColor(i, strip.Color(0,0,0, strip.WhiteGamma(j)));
        }
        if (wait > 0) {
            delay(wait);
        }
        strip.show();
    }
    for(int j = 255; j >= 0 ; j -= increment){
        for(uint16_t i=0; i<strip.numPixels(); i++) {
            strip.setPixelColor(i, strip.Color(0,0,0, strip.WhiteGamma(j)));
        }
        if (wait > 0) {
            delay(wait);
        }
        strip.show();
    }
}

void setup()
{
	Serial.begin(BAUD_RATE);
    strip.begin();
    strip.setBrightness(BRIGHTNESS);

    strip.show(); // Initialize all pixels to 'off'

    pulseWhite(1, 2);

    strip.show();
}

void on_pattern_complete()
{
    if (strip.ActivePattern == FADE) {
        if (strip.Color2 == strip.Color(0, 0, 0)) {
            strip.ActivePattern = NONE;  // stop the strip if fading to off
            strip.show();
        }
        else {
            strip.Reverse();
        }
    }
}

uint32_t char_to_color(char color_char) {
    switch (color_char) {
        case 'w': return strip.Color(0, 0, 0, 255);
        case 'b': return strip.Color(0, 0, 255);
        case 'r': return strip.Color(255, 0, 0);
        case 'g': return strip.Color(0, 255, 0);
        case 'y': return strip.Color(255, 255, 0);
        default: return strip.Color(0, 0, 0);
    }
}

void fade_to_off() {
    strip.Fade(strip.Color(0, 0, 0, 255), strip.Color(0, 0, 0, 0), 256, 5);
}

void set_to_white() {
    strip.ActivePattern = NONE;
    strip.ColorSet(strip.Color(0, 0, 0, 255));
}


void temperature_crossfade(uint16_t cross_fade_index) {
    if (strip.ActivePattern != FADE_EXTERNAL) {
        strip.FadeExternal(cool_color, hot_color, 256);
    }
    strip.FadeExternalUpdate(cross_fade_index);
}

void set_rainbow_type(char rainbow_type)
{
    if (rainbow_type == 's') {
        strip.RainbowCycle(50);
    }
    else if (rainbow_type == 'f') {
        strip.RainbowCycle(5);
    }
}

void loop()
{
    if (Serial.available()) {
        String command = Serial.readStringUntil('\n');
    	switch(command.charAt(0)) {
    		case 'o': fade_to_off(); break;
    		case 'w': set_to_white(); break;
    		case 't': temperature_crossfade(command.substring(1).toInt()); break;
    		case 'r': set_rainbow_type(command.charAt(1)); break;
    		case 'f': strip.Fade(char_to_color(command.charAt(1)), strip.Color(0, 0, 0, 1), 255, 5); break;
    		case 'c': strip.Scanner(char_to_color(command.charAt(1)), 50); break;
    	}
    }

    strip.Update();
}
