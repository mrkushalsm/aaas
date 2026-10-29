WORKSPACE ?= /run/media/mrkus/Homework/aaas-workspace
DX ?= $(WORKSPACE)/sources/prebuilts-build-tools-qpr2/common/bin/dx
JAVAC ?= javac
BUILD_DIR ?= $(WORKSPACE)/tmp/m1e_display_broker_build
OUT ?= $(WORKSPACE)/tmp/m1e_aaas_display_broker.dex

all: $(OUT)

$(OUT): AaasDisplayBroker.java
	mkdir -p $(BUILD_DIR) $(dir $(OUT))
	$(JAVAC) --release 8 -d $(BUILD_DIR) $<
	cd $(BUILD_DIR) && $(DX) --dex --min-sdk-version=35 --output=$(OUT) com/aaas/display/*.class

clean:
	rm -rf $(BUILD_DIR) $(OUT)

.PHONY: all clean
