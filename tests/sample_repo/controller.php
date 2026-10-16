<?php

interface ActionInterface {
    public function handle();
}

class HomeController implements ActionInterface {
    public function handle() {
        return "Home response";
    }
}
